# Riot Commander - next session: the next 5 open rows

## CONTEXT (do not re-derive)

- ENGINE **1.248.0**, patch 16.14.1. DS `agents/daemon_slayer/tests` **9621 passed /
  1 skipped / 4617 subtests**; RC `tests/` **13083 passed / 106 skipped / 448 subtests**
  (both measured 2026-07-25). Tree clean, pushed. DS `:8893` serving 1.248.0.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.248.0 + `docs/LEDGER.md` 1048 +
  `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` **PART 8**.
- Shipped last session, all DEFAULT-OFF: `apply_crit_conversion` (new
  `_crit_conversion_overrides.py`, Ashe Frost Shot, plumbed through `rank_items` AND
  POST /rank), Quinn seeded into `_KIT_CONVERSION` + a per-champion
  `marksman_offclass_exempt.json` row, `apply_ability_base_overrides` (new
  `_ability_base_overrides.py`, 6 champions), `score_by` plumbed through
  `core/build_order.py` / `core/build_order_precompute.py` /
  `tools/daemon_slayer_build_orders_generate.py`, `_ALLY_REACH_INCLUDED` (4 champions),
  and `kit_conversion_strength` route-exposed on POST /rank.

## METHOD (standing directive - this is a LOOP)

Five open **non-gated** items per session. Probe every row to PROBED before building -
five consecutive sessions have now found mis-filed rows, and the last one found **4 of 4
survivors mis-scoped by their own filing**. Parallel worktree agents on disjoint file
sets, one Claude as sole merger holding every shared seam. Self-adjudicate; do not gate
on the operator mid-run. End with `/done` plus a full next-session prompt.

Before believing a row is unbuilt: `git log -5 -- <cited file>`, grep `docs/specs/**` and
`tests/**`, and check the row's AGE. Mis-files come in two classes - answer-already-on-disk
and intended-behavior-as-bug.

## CANDIDATE ROWS (from `docs/OPEN_ITEMS_REVIEW_2026-07-25.md`, none pre-probed)

The list is a menu, not a verdict.

1. **A-21 / RM-90 S3 - the support-item schema lift.** This is now the single
   best-evidenced open row, and last session's measurement is the argument for it:
   `_item_ally_grant.py:95-105` hard-excludes Knight's Vow 3109, Zeke's 3050, Bandlepipes
   2524 and Solstice Sleigh 3876, so Locket is the ONLY priced support core item and the
   `team_blended` seam - which IS live and champion-selective at the ranking layer - can
   never win a greedy build slot. **Do NOT re-attempt S1/S2; they shipped and the
   order-level acceptance criterion was REFUTED at the coefficient layer.**
2. **A-12 / RM-46 Ashe, Ranger's Focus half.** The Frost half shipped; modelling Ranger's
   Focus as an AS steroid is untouched. Note the shipped seam's limit: `kit_conversion.py`
   already names why move-speed value (Spectral Waltz) is unreachable by any DPS objective.
3. **The A-07 mage-cluster block, with two terms now named.** PART 7 named them while
   closing A-16: `ability_dps.py` holds ZERO `slow` tokens (Rylai's is registered
   `defensive_only=True` at `_effects_data.py:1783-1791`), and `ability_dps.py:44-45`
   excludes `P` abilities, so a signature passive like Darkness Rise is invisible to its
   own scorer. That is a scorer-coverage row, not a per-champion row.
4. **The RM-37 / RM-42 / RM-38 successor row** filed by PART 7: the champion-invariant
   carry on-hit bias across 12+ ADCs, where the six `core/ds_champion_fight_length.py:105`
   members are the built-in control group and the real question is whether that map should
   be a hand-curated list at all. Falsifiable, unlike its three parents.
5. **A-95b: source the Locke / Zaahen kits.** Blocked upstream in Meraki's 171-champion
   bulk map; the certification half (A-26 / RM-95a) already shipped.
6. Any remaining `AS-FILED` row in the PART 1-6 inventory tables. Re-probe before building.

## DO NOT PICK

- **A-16 / RM-82 Mordekaiser** - CLOSED, BLOCKED-UNFALSIFIABLE. Inherits the A-07
  `ds.ability` block; the gate-ON re-run with `apply_ability_amps:true` was byte-identical,
  so it is not a flag-OFF negative. Fold into the mage cluster as a fourth instance.
- **A-10 / RM-37 + RM-42 Lucian/Akshan** - CLOSED, unmeasurable AS FILED. Dies on its own
  control (IE at exactly #11 for six ADCs; twelve emit a byte-identical shipped order); the
  `coherence_rerank` half is INTENDED with DO-NOT-RETUNE constants. Pick the successor row
  above instead.
- **A-21 S1 / S2** - shipped. Do not re-run them expecting build-table movement.
- **A-27 / RM-114, A-30 / R129, A-11 / RM-44, A-15 / RM-80** - closed in earlier sessions.
- The ROADMAP relocation pass (`b4d1ee56`) - done.

## HAZARDS carried forward

- **The ENGINE bump needs THREE doc sites the in-repo CHANGELOG does not cover:**
  `docs/DAEMON_SLAYER.md` status banner (version AND test count), `Share/CHANGELOG.md`
  (`## <prev> -> <new> (YYYY-MM-DD)` at the top of "Recent releases"), and the
  `Share/README.md` release-history list. `tools/ds_share_sync.py` deliberately does NOT
  rewrite changelog history, so `--check` reads GREEN while the public history silently
  loses a release.
- **Bump by QUOTED literal only** (`"1.248.0"` / `'1.248.0'`), never by bare string: `.md`
  prose mentions of an old version are historical MEASUREMENT CITATIONS and rewriting them
  falsifies the record. Exclude `.claude` (live agent worktrees are full repo copies).
  Last session: **256 code files / 295 occurrences**. The `docs/DAEMON_SLAYER.md` banner is
  a bare-prose EXCEPTION and must be hand-edited - it is a live statement, not a citation.
- **Re-run the Share sync AFTER any late test edit.** Editing a DS test after the sync
  leaves the mirror drifted and fails `tests/test_ds_share_sync_determinism.py` at the very
  end of a 22-minute run. Cost last session: one full re-run.
- **Exit code is NOT ground truth.** Last session's `tests/` run reported exit 0 on a run
  whose summary line said `1 failed`. Redirect pytest to a FILE and read the summary line.
  A `tests/` run takes **~22 minutes** - launch it in the background and do docs work while
  it runs, and re-run it FRESH after any late fix.
- **A NEW-TEST-IN-THE-MIRROR TRAP:** any new test under `agents/daemon_slayer/tests/` that
  imports a HOST package (`core.*`) at module level MUST be added to `_HOST_DEPENDENT_TESTS`
  in `tools/ds_share_sync.py`. Check every new test's imports. (Last session's six new DS
  tests were all clean, so this did not bite.)
- **Build-order tables: THREE families across TWO keyspaces; a bump needs ALL of them:**
  ```
  python tools/daemon_slayer_build_orders_generate.py --mode all        (--mode, NOT --champions)
  python -m core.build_order_precompute --static --mode all --champions all
  python -m core.build_order_variants   --static --mode all --champions all
  ```
  Family A takes ~160s and prints; B and C write **silently with exit 0 and zero stdout** -
  confirm via `git status data/`. **Then CORROBORATE "no movement" with a stamp-stripped
  payload diff** (recursively drop `engine_version` / `generated_at` / `version`, then
  compare). A 1-2 line numstat is NOT proof on a single-line JSON file. All 9 files read
  SAME last session, which is the correct result when every seam is DEFAULT-OFF.
- **ENGINE bump ritual: bump -> RESTART `:8893` -> VERIFY `/health` reads the NEW version
  -> regen -> measure.** Restart in **PowerShell**:
  `taskkill /F /PID <pid>; schtasks /Run /TN "RC-DaemonSlayer"` (Git Bash mangles `/F` and
  `/Run` into paths). Get the pid with `Get-NetTCPConnection -LocalPort 8893 -State Listen`.
- **`git apply` of a worktree diff FAILS in this repo** (EOL / whitespace mismatch). Merge
  a slice by extracting its committed blobs: `git -C <worktree> show HEAD:<path> > <path>`.
- **The precommit Share hook corrupts worktree indexes.** It hit TWO of four agents last
  session with ~500 spurious staged deletions after their commits; both repaired with
  `git reset`, and both commits were intact. **Check `git show --stat HEAD` after every
  commit.** Do not commit from the main tree while an agent worktree is live.
- **A plumb can SILENTLY SUPERSEDE a monkeypatch.** Last session's `apply_crit_conversion`
  plumb turned a build agent's `functools.partial(compute_dps, apply_crit_conversion=True)`
  into a no-op, because a call-time keyword overrides a partial keyword. Test failures after
  a plumb are usually real premise decay, not flakes - repair the premise, never the
  assertion.
- **A default flip makes its own tests vacuous** (`feedback_default_flip_weakens_tests`).
- **Never probe at an empty item list.** That artifact has now manufactured FIVE false
  headlines (latest: the filed Lucian "Essence Reaver raw #4"; real depth rank is #10).
- **DS probe traps:** `POST /rank` is the CARRY scorer and silently ignores
  `enemy_ad_share` / `enemy_ap_share` (use `/rank-<archetype>`; there is NO `/rank-hybrid`
  - bruisers use `/rank-bruiser`); body key is `items`, not `item_ids`; `top` defaults to
  40; always pass explicit non-zero target stats. **DS is plain HTTP on `:8893`** - HTTPS
  returns curl exit 35. In-process, `rank_items(DataSnapshot.load(), champion_id, level,
  ...)` returns a `RankResult`.
- **"Never run an extract in the same commit as a table regen" is UNVERIFIED** and roughly
  contradicts `feedback_engine_bump_ritual_order`. Do not design a slice around it. The
  sibling hazard - never `--force` a Meraki re-extract, because `latest` is mutable - IS
  confirmed at three independent sites.
- **`ability_staleness.json` lies.** Its committed baseline predates the `62e4a410` shape
  fix (it still reports Mordekaiser Q at 389 pct against a true 4.6 pct). Regenerate it
  first or bypass it, as last session did.

## OPEN, HELD FOR AN OPERATOR CALL

- **K'Sante Q Ntofo Strikes** at `bonus_armor_pct` 40 / `bonus_mr_pct` 40 - a clean
  linear resist-to-damage form that the documented K'Sante **P** reject
  (`_passive_damage_overrides.py:839-843`) does not cover. Held OUT of
  `_resist_damage_coupling.py`. Promoting it is a valuation call, not a data question.
- **Two live-gated rows** in `docs/LIVE_GAME_GATED_SYNC.md`: **G2-44** (the carry-route
  `exclude_off_axis_items` default-ON flip - payoff is concrete: Twitch serves Lich Bane
  #7 today) and the A-39 boot-CC default-ON flip. Both are do-not-flip-blind.
- **The six DEFAULT-OFF seams shipped 1.247.0-1.248.0 are all still OFF.** Flipping any of
  them on by default is an operator valuation call, not a build task.

## EXPECT

Measure before/after for every item and report the delta honestly, **including "no
movement" - but PROVE a no-op came from the NEW code path** (a spy recording the kwargs
it received is the technique that keeps working; a stamp-stripped payload diff is the
technique for tables). Report the exact pass/fail counts you observed THIS run; never
carry a prior or subagent-reported count forward. Then `/done`, and hand over the next 5.

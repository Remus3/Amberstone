# Riot Commander - next session: clean up ROADMAP.md, THEN the next 5 open rows

## 0. FIRST TASK, OPERATOR-DIRECTED 2026-07-25: clean up `ROADMAP.md`

This is the priority for the session and it is not optional. `ROADMAP.md` is
**78500-79500 bytes against the 81920 ceiling** in `tests/test_doc_size_budget.py`
(`ROADMAP_MAX = 80 * 1024`). Measure it first (`(Get-Item ROADMAP.md).Length`), because
three sessions in a row have each spent 600-1500 bytes of the remaining headroom on
status flips. It will hit the budget and fail CI within about two more sessions.

What the file has become: a mix of live open work, SHIPPED entries kept in place with
verdicts appended, and BLOCKED entries carrying full measurement narratives. The
cleanup is a RELOCATION job, not a deletion job.

- **The destination already exists:** `docs/ROADMAP_HISTORY.md` (unbudgeted). Two prior
  relocations are already recorded there (a 2026-07-18 block for the RM-35..RM-48 sweep
  narrative, a 2026-07-25 block for RM-79..RM-98). Follow that established pattern - a
  dated block, verbatim text, and a one-line pointer left behind in `ROADMAP.md`.
- **Relocate:** every SHIPPED row's narrative (keep a one-line "SHIPPED at ENGINE
  x.y.z, see LEDGER n" stub), and every BLOCKED row's measurement evidence (keep the
  verdict plus the named prerequisite, drop the numbers to history). This session alone
  added long verdicts to RM-35, RM-44 and RM-114 that belong in history now.
- **Do NOT relocate or reword:** the "DS per-champion meta-valuation sweep" section - it
  carries load-bearing PROBE HAZARD text that agents read to avoid the `item_ids=[]` and
  `/rank`-vs-`/rank-<archetype>` traps. It stays in `ROADMAP.md` verbatim.
- **Do NOT delete anything.** `feedback_no_history_rewrite` - the ledger and roadmap
  files are append-or-relocate only.
- **Verify:** `python -m pytest tests/test_doc_size_budget.py tests/test_docs_*.py -q`,
  and re-measure the byte count. Target leaving at least 8-10 KB of headroom so the
  next few sessions do not immediately re-breach it. Also check whether any
  `ROADMAP.md` cross-reference elsewhere in the repo (grep for `ROADMAP.md#`) still
  resolves after the move.
- While you are in there: `CLAUDE.md:135` still says "20,190 tests", which is wrong.
  The measured counts are DS **9546** and RC `tests/` **13061**. This session already
  fixed CLAUDE.md's stale `ENGINE_VERSION 1.244.0` pointer; the test count is the last
  known stale number in that file.

## CONTEXT (do not re-derive)

- ENGINE **1.247.0**, patch 16.14.1. DS `agents/daemon_slayer/tests` **9546 passed /
  1 skipped / 4547 subtests**; RC `tests/` **13061 passed / 106 skipped / 448 subtests
  / 0 failed** (both measured 2026-07-25). Tree clean, pushed. DS `:8893` serving
  1.247.0.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.247.0 + `docs/LEDGER.md` 1046 +
  `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` **PART 6**.
- Shipped this session, all DEFAULT-OFF: `apply_resist_damage_coupling` /
  `resist_coupling_strength` (new `_resist_damage_coupling.py`), Terminus SR `3302`
  Light resists in `_item_resist_grants.py`, `exclude_off_axis_items` on the CARRY
  route (`rank.rank_items` + `/rank`), and `boot_utility.comp_cc_signal` +
  `enemy_champions` on `core/build_order._select_boots*` / `plan_build_order`.
- **Three rows CLOSED without code and they must NOT be re-opened:** A-27 / RM-114
  (NEXT BUY DS fallback already shipped DEFAULT-ON as `core/next_buy_fallback.py`),
  A-30 / BACKLOG R129 (sub-fix B IS `apply_ad_axis_ability_damage`; building
  `blend_ability_axis` would REGRESS), A-11 / RM-44 (BLOCKED-UNFALSIFIABLE).

## METHOD (standing directive - this is a LOOP)

After the ROADMAP cleanup: five open **non-gated** items. Probe every row to PROBED
before building - grep the cited symbol, hit the live route, read the spec. Build as
parallel worktree agents on **disjoint file sets**, with you as **sole merger** holding
every shared seam: `ENGINE_VERSION`, both CHANGELOGs, **all three table regens across
BOTH keyspaces**, Share sync, living docs. Then `/done` + the next prompt.

**Operator decisions do NOT block.** When a row needs a default-ON/OFF or scope call,
dispatch a **self-adjudicating agent with scope to decide**, and require the evidence it
decided on, not just the verdict.

**Grep `docs/specs/**` and `tests/**` for every cited id/symbol BEFORE touching
implementation code** - that step has now caught **9** mis-files in three sessions.

**NEW, and this is the lesson of this session: also check the row's AGE against
`git log` for the file it cites.** Three of the five rows this session were closed by
work that had already landed - one of them a single day before the row was written. A
tier tag (PROBED / SOURCE-READ / AS-FILED) records how well a row was probed, never how
recently. Cheapest possible first move on any row: `git log --oneline -5 -- <cited file>`.

**When open non-gated items run dry, roll this queue:** DS sweep -> UI/UX -> repo /
structure / security -> future-backlog -> research.

## CANDIDATE ROWS (all from `docs/OPEN_ITEMS_REVIEW_2026-07-25.md`, none pre-probed)

Pick five AFTER the ROADMAP cleanup, and probe each one first - the list below is a
menu, not a verdict.

1. **A-03 / RM-81 re-source the 6 champions that matter.** 75 of 171 carry drifted
   values but only 6 change any ranked order, 2 touch a top-5, 0 change a recommended
   core. Re-source 6, not 75. **Scheduling hazard: never re-run
   `tools/daemon_slayer_extract.py` in the same commit as a table regen**, and never
   `--force` a Meraki re-extract (the `latest` endpoint is mutable). If this row is
   picked it probably wants its own commit ahead of any ENGINE bump.
2. **A-12 / RM-46 Ashe Frost + Ranger's Focus.** Crits deal no bonus damage (crit
   chance converts to flat AD) so IE's multiplier is largely dead on her; Phantom
   Dancer dead-last even in a 6-item self-whitelist. Aphelios is the named contrast
   twin. **Run the falsifiability gate FIRST** - pick the control, prove separation.
3. **A-16 / RM-82 Mordekaiser.** Rylai's / Riftmaker buried under a never-built AP-amp
   plus magic-pen lead. Same gate applies.
4. **A-20 / RM-89 Quinn.** The first champion carrying BOTH RC-1 and RC-2, filed as the
   proof that the shipped L1 kit-conversion lever is necessary and provably
   INSUFFICIENT. Read what "insufficient" was measured to mean before designing.
5. **A-21 / RM-90 support-cohort build-order collapse.** Verified against the shipped
   `build_orders_sr.json`; the prior Alistar / Blitzcrank / Braum / Bard / Rakan
   REFUTEs were judged TOO LENIENT. **Check the shipped build order before accepting
   any new team-aura REFUTE.** Note the A-11 measurement this session found the tank
   route emitting a byte-identical 6-item order across 6 champions - the support
   cohort may be the same class of defect, which would make this row bigger than 1S.
6. **A-10 / RM-37 + RM-42 empowered-auto crit machinery (Lucian, Akshan).**
   Lightslinger double-tap + Dirty Fighting 200pct crit double-shot unmodelled, and
   `coherence_rerank` additionally DOCKS Lucian's #1 item Essence Reaver from raw #4 to
   #10-18. Shared machinery, batch them.
7. **The A-18 follow-through, now that `ds.ehp` HAS a champion channel.** A-11 / RM-44
   was blocked on "champion-sensitivity in `ds.ehp`" and this session shipped the first
   such lane (sort-only, registry-keyed). Whether an AP-damage-tank credit can ride the
   same shape is an open DESIGN question, not a filed row - it needs its own probe, and
   the RM-44 verdict says rerouting is NOT the answer.

## DO NOT PICK

- **A-27 / RM-114, A-30 / R129, A-11 / RM-44** - closed this session, evidence in
  PART 6. A-11 specifically is BLOCKED on a schema lift, not on effort.
- **A-15 / RM-80 Master Yi** - REFUTED + CLOSED 2026-07-25. `ds.onhit` is the on-hit-AP
  scorer (roster Gwen / Kayle / KogMaw); Yi is pure AD.
- **A-24 / RM-93 support-quest candidacy** - REFUTED, deny is deliberate and
  test-pinned (`test_sr_quest_line_deny_rm93.py`).
- **A-25 / RM-94 Mejai's** - SHIPPED at 1.243.0 (`bonus_ap_stacked=25.0`).
- **A-14 / RM-79 + RM-95b Locke / Zaahen ability data** - BLOCKED UPSTREAM (absent from
  Meraki's 171-champ bulk map). Do NOT synthesize their kits.
- **A-23 / RM-92 ability-haste residual** - SIZED, verdict DEFER
  (`docs/specs/SCOPE_rm92_ability_haste.md`).
- **A-07 / RM-40 / RM-45 / RM-47 mage cluster** - MEASURED BLOCKED on a scorer
  prerequisite; GAP champion and its own control are indistinguishable.
- **A-09 / RM-36 + RM-38 AD-caster pool** - A-01 already MEASURED un-filtering as
  necessary and NOT sufficient (108 -> 112, ZERO top-8 changes).
- **`RC_VISION_MERGE_STRICT` default-ON**, and the two new gated rows below - LIVE-GATED,
  not headless-drainable.

## HAZARDS carried forward

- **The ENGINE bump needs THREE doc sites the in-repo CHANGELOG does not cover:**
  `docs/DAEMON_SLAYER.md` status banner (version AND test count), `Share/CHANGELOG.md`
  (`## <prev> -> <new> (YYYY-MM-DD)` at the top of "Recent releases"), and the
  `Share/README.md` release-history list. `tools/ds_share_sync.py` deliberately does NOT
  rewrite changelog history, so `--check` reads GREEN while the public history silently
  loses a release; only `tests/test_ds_share_changelog_freshness.py` catches it.
- **Bump by QUOTED literal only** (`"1.247.0"` / `'1.247.0'`), never by bare string:
  `.md` prose mentions of an old version are historical MEASUREMENT CITATIONS and
  rewriting them falsifies the record. This session's blanket-census would have
  rewritten 12 such citations in `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` alone. Exclude
  `.claude` (live agent worktrees are full repo copies). True count this session: **249
  code files / 283 occurrences**.
- **A NEW-TEST-IN-THE-MIRROR TRAP, cost 3 test failures this session.** Any new test
  under `agents/daemon_slayer/tests/` that imports a HOST package (`core.*`) at module
  level MUST be added to `_HOST_DEPENDENT_TESTS` in `tools/ds_share_sync.py`, then
  re-synced. Otherwise `tests/test_ds_share_host_dependent_tests_excluded.py` and
  `tests/test_ds_share_sync_determinism.py` fail. Check every new test's imports before
  running `tests/`.
- **Exit code is NOT ground truth** (a prior session saw exit 0 on a run whose summary
  said `3 failed`). Redirect pytest to a FILE and read the summary line. Also: a
  `tests/` run takes **~24 minutes** - launch it in the background and do docs work
  while it runs, and re-run it FRESH after any late fix rather than reasoning about
  which failures were stale.
- **Build-order tables: THREE families across TWO keyspaces; a bump needs ALL of them:**
  ```
  python tools/daemon_slayer_build_orders_generate.py --mode all        (--mode, NOT --champions)
  python -m core.build_order_precompute --static --mode all --champions all
  python -m core.build_order_variants   --static --mode all --champions all
  ```
  Family A takes ~215s and prints; families B and C write **silently with exit 0 and
  zero stdout** - confirm via `git status data/`. **Then CORROBORATE "no movement" with
  a stamp-stripped payload diff against the committed blobs** (this session's
  `scratchpad/stampcheck.py` pattern: `git show HEAD:<file>` vs working tree, recursively
  dropping `engine_version` / `generated_at` keys, then diff the payload). A 1-2 line
  numstat is NOT proof on a single-line JSON file.
- **ENGINE bump ritual: bump -> RESTART `:8893` -> VERIFY `/health` reads the NEW
  version -> regen -> measure.** Restart in **PowerShell**:
  `taskkill /F /PID <pid>; schtasks /Run /TN "RC-DaemonSlayer"` (Git Bash mangles `/F`
  and `/Run` into paths). Get the pid with
  `Get-NetTCPConnection -LocalPort 8893 -State Listen`.
- **`git apply` of a worktree diff FAILS in this repo** (EOL / whitespace mismatch -
  it failed on 5 of 6 files this session). Merge a slice by copying its owned files
  outright, and hand-apply any edit that lands in a file another slice also owns.
- **A slice's "+1 line" report is not a merge instruction.** One slice reported a
  one-line `ehp.py` change whose 3-line anchor matched TWICE. Confirm the call site is
  unique (grep the callee, not the argument block) before applying.
- **Check `git show --stat HEAD` for unintended staged deletions after every commit**
  (the precommit hook runs its own sync). Zero deletions this session - keep verifying.
- **A default flip makes its own tests vacuous** (`feedback_default_flip_weakens_tests`).
  Pins for a now-default value must derive it from the feed, and a mutation check must
  show real failures. Two mutation checks earned their keep this session: one caught a
  normalization that cancelled the very percentages it was meant to weigh, and one
  caught a knob bound at `def` time that was documented as runtime-tunable.
- **Never probe at an empty item list.** That artifact has now manufactured FOUR false
  headlines (latest: "BotRK #1 for Miss Fortune"). And do not anchor a magnitude
  measurement on the engine still recommending the item you are demoting.
- **DS probe traps:** `POST /rank` is the CARRY scorer and silently ignores
  `enemy_ad_share` / `enemy_ap_share` (use `/rank-<archetype>`; there is NO
  `/rank-hybrid` - bruisers use `/rank-bruiser`); body key is `items`, not `item_ids`;
  `top` defaults to 40; always pass explicit non-zero target stats (route defaults are
  0.0 and a zero-HP target nullifies every percent-max-HP effect). **DS is plain HTTP
  on `:8893` - HTTPS returns curl exit 35.** In-process,
  `rank_items(DataSnapshot.load(), champion_id, level, ...)` returns a `RankResult`
  whose rows live under **`.ranked`** (it is not iterable).
- **THE FALSIFIABILITY GATE IS NOW MANDATORY ON ANY PER-CHAMPION VALUATION ROW.** Three
  clusters are now measured BLOCKED-UNFALSIFIABLE for the same reason (RM-40/45/47,
  RM-44 + siblings RM-51 / RM-55, RM-35 clause 1): the GAP champion and its own REFUTE
  control return the same answer, so no test can distinguish the right fix from a wrong
  one. Pick the control FIRST, prove separation, and only then design. A scorer whose
  objective contains no term for the thing the row is about cannot be fixed by a
  coefficient - `ds.ehp`'s `blended_ehp` has no damage term on any axis, and `ehp.py`
  imports no abilities at all.
- **Deny / sibling sweeps go by ID SUFFIX across every map, never by name.** `3172`
  Gunmetal Greaves and `223172` Zephyr are DIFFERENT items. Meraki `rank: DISTRIBUTED`
  is NOT a pollution test. Map ids wired: `{SR:11, ARAM:12, ARENA:30, BRAWL:35}`; map
  **21 is Nexus Blitz** and is unwired, so a map-21-only item is pool-illegal everywhere.
- **Doctrine B has teeth: a mirror with no on-disk magnitude gets NOTHING.** Arena
  `223302` was refused this session rather than inheriting SR's number by ratio. The
  pattern for that is `_ITEM_RESIST_UNSOURCED_MIRRORS` (mirroring
  `_item_general_dr._GENERAL_DR_UNSOURCED_MIRRORS`).
- `tools/ds_feed_index.py` `KNOWN_STAMP_LAG` is NOT what its guard test reads - edit the
  `.py`, then run `python tools/ds_feed_index.py --write`.

## OPEN, HELD FOR AN OPERATOR CALL

- **K'Sante Q Ntofo Strikes** at `bonus_armor_pct` 40 / `bonus_mr_pct` 40 - a clean
  linear resist-to-damage form that the documented K'Sante **P** reject
  (`_passive_damage_overrides.py:839-843`) does not cover. Held OUT of
  `_resist_damage_coupling.py`. Promoting it is a valuation call, not a data question.
- **Two NEW live-gated rows** were added to `docs/LIVE_GAME_GATED_SYNC.md` as **G2-44**
  (the carry-route `exclude_off_axis_items` default-ON flip - payoff is concrete: Twitch
  serves Lich Bane #7 today) and, unfiled but adjacent, the A-39 boot-CC default-ON
  flip. Both are do-not-flip-blind.

## EXPECT

Measure before/after for every item and report the delta honestly, **including "no
movement" - but PROVE a no-op came from the NEW code path** (a spy recording the kwargs
it received is the technique that keeps working; a stamp-stripped payload diff is the
technique for tables). Report the exact pass/fail counts you observed THIS run; never
carry a prior or subagent-reported count forward. Then `/done`, and hand over the next 5.

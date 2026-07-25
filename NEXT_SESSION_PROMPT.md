# Riot Commander - next session: the next 5 open rows

## CONTEXT (do not re-derive)

- ENGINE **1.249.0**, patch 16.14.1. DS `agents/daemon_slayer/tests` **9636 passed /
  1 skipped / 4617 subtests**; RC `tests/` **13110 passed / 106 skipped / 460 subtests**
  (both measured fresh 2026-07-25 AFTER every doc edit). Tree clean, pushed. DS `:8893`
  serving 1.249.0.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.249.0 + `docs/LEDGER.md` 1049 +
  `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` **PART 9**.
- Shipped last session: the alias/mirror build-order dedup (**DEFAULT-ON**, the only
  table-moving change - Viego and Samira were shipping FIVE-item builds),
  `apply_passive_aura_damage` (DEFAULT-OFF, new `per_second` cadence in
  `_passive_damage_overrides.py`, Mordekaiser's Darkness Rise),
  `apply_crit_conversion` + `kit_conversion_strength` plumbed through
  `core/daemon_slayer_client.py`, and `--full-roster` (DEFAULT-OFF) on all four sidecar
  extractors.

## METHOD (standing directive - this is a LOOP)

Five open **non-gated** items per session. Probe every row to PROBED before building -
**six consecutive sessions have now found mis-filed rows**, and last session THREE of the
five named rows closed without any code while the single most valuable fix came from a
tail observation in a probe report, not from the menu. Parallel worktree agents on
disjoint file sets, one Claude as sole merger holding every shared seam. Self-adjudicate;
do not gate on the operator mid-run. End with `/done` plus a full next-session prompt.

Before believing a row is unbuilt: `git log -5 -- <cited file>`, grep `docs/specs/**` and
`tests/**`, and check the row's AGE. Mis-files come in two classes - answer-already-on-disk
and intended-behavior-as-bug.

**Read every probe report's tail.** Two of last session's five probes surfaced defects
nobody had filed (the alias duplicate, and the latent Locket `3190`/`323190` mirror pair).
Those were worth more than three of the five menu rows.

## CANDIDATE ROWS (from `docs/OPEN_ITEMS_REVIEW_2026-07-25.md`, none pre-probed)

The list is a menu, not a verdict.

1. **The `ds.ehp` champion-sensitivity schema lift.** Three separate rows have now
   independently converged on this as their blocker and named it as their own successor:
   **A-11 / RM-44** (Amumu magic-tank AP rush - Abyssal is #14 for eight tanks alike),
   **A-22 / RM-91** (HP-as-damage - Randuin's is engine #1 for five tanks and in the real
   core of none), and **A-21 / RM-90 S3** (the support-cohort collapse is a self-EHP
   deficit of 1700-4800 per slot, not an ally-grant gap). `ehp.py` imports no abilities
   and `blended_ehp` at `ehp.py:2095-2099` carries no damage term on any axis. The
   1.247.0 `_resist_damage_coupling.py` seam is the first slice of exactly this. **This is
   the single best-evidenced open row and it is now three rows deep in agreement.**
2. **A-26 / RM-95b B2** - promote wiki `leveling` to typed damage blocks. B1 shipped, so
   the roster cap is gone, but `wiki_ability_stats.json` carries NO `leveling` key and no
   damage field for ANY champion, and DDragon supplies none either. Locke's
   `/rank-assassin` `baseline_burst` still reads **0.0** against Zed 938.46. Costed at
   1-1.5 sessions in `docs/specs/DECISION_cdragon_cross_reference.md:502-509`.
3. **A-13 / RM-48 Azir soldier axis + the pet-DPS cohort** (siblings Yorick / Malzahar /
   Heimerdinger; overlaps RM-97 pet damage). No scorer models a pet or summon stream.
4. **A-17: RM-83 Naafiri / RM-85 Nasus / RM-96 Zilean / RM-97 Zyra** - four remaining
   per-champion GAP specs, each its own RED-first slice.
5. **A-32 / R190 kit-penetration tails (a)-(d).** (a) Annie R magic pen absent from
   `_ANTITANK_REGISTRY`; (b) registry rows carry no `axis` field; (c) Amumu P is
   registered SHRED 0.6 but 16.14.1 is a 10 pct bonus-true vulnerability; (d) magnitudes
   are max-rank only. **(e) is a schema lift and gates nothing else - leave it.**
6. Any remaining `AS-FILED` row in the PART 1-6 inventory tables. Re-probe before building.

## DO NOT PICK

- **A-21 / RM-90 S3** - CLOSED BLOCKED-UNFALSIFIABLE. The ally lane's ceiling is 993.6 raw
  HP (amortized 496.8) against a 1700-4800 per-slot self-EHP deficit; the amortizer sweep
  needs p=1.0 (an invented constant) before ANY order moves. Population is **1, not 4** -
  all four `_item_ally_grant.py:95-105` exclusions verify TRUE against their own feeds.
  "Locket is the ONLY priced support core item" is also FALSE (Redemption 3107, Mikael's
  3222, Echoes of Helia 6620). **Do NOT file a fifth ally-grant registry row.**
- **A-12 / RM-46 Ranger's Focus (AS half)** - CLOSED BLOCKED-UNFALSIFIABLE. Also MIS-NAMED:
  Ranger's Focus is Ashe's **Q**; her W is Volley. A +45 pct AS proxy moves head-4 not at
  all and yields one adjacent swap that **Caitlyn and Master Yi show identically**. If
  anyone returns here, the target is the **flurry asymmetry** (110-140 pct total AD per
  auto while on-hit applies ONCE), not the AS steroid - and it owes the gate-3 plumb below.
- **The RM-37 / RM-42 / RM-38 successor** - CLOSED-WITH-A-FINDING. 125 scalar quantities
  scanned, ZERO separate the six-member fight-length map; the one corpus source with
  sufficient n does not reproduce it either. **FENCE: an allow-map entry is an operator
  meta assertion validated by live play, not a threshold.**
- **A-07 TERM 1 (slow credit / flipping Rylai's `defensive_only`)** - BLOCKED. 88 of 161
  registered champions carry a SLOW entry, so it lifts GAP Aurora and control Anivia
  together. TERM 2 shipped; Rylai's did NOT move (#24 ON and OFF).
- **A-16 / RM-82** - TERM 2 shipped 1.249.0. Note the A-07 block premise itself is now
  REFUTED: a roster-wide sweep returns 78 distinct top-8 heads (20 among 84 AP champions)
  and control Anivia is already alone in its class. Four sessions measured a top-3
  stat-dominance artifact over a hand-picked 4-champion sample and called it a block.
- **A-27 / RM-114, A-30 / R129, A-11 as a standalone row, A-15 / RM-80, A-24 / RM-93** -
  closed in earlier sessions.

## HAZARDS carried forward

- **A DS seam has THREE gates, not two: engine, HTTP route, and CLIENT DISPATCHER.**
  `core/daemon_slayer_client.py` `rank_for` / `rank_for_primary_archetype` is the chokepoint
  every live coach tick AND every generated table passes through. Two seams shipped at
  1.248.0 cleared gates 1 and 2 and still moved **0 of 27 champions** on the client path.
  **`assume_passive_as_stacks` is STILL stuck at gate 2** - `grep assume_passive_as_stacks
  agents/daemon_slayer/rank.py` returns zero. Probe seams through the CLIENT, with a spy
  on the request layer. Memory: `reference_ds_kit_conversion_not_route_exposed`.
- **The ENGINE bump needs FOUR doc sites:** `agents/daemon_slayer/CHANGELOG.md` (guarded -
  `test_changelog_tracks_engine_version.py` fails the suite if you skip it), plus the three
  the guard does NOT cover: `docs/DAEMON_SLAYER.md` status banner (version AND test count),
  `Share/CHANGELOG.md` (`## <prev> -> <new> (YYYY-MM-DD)` at the top of "Recent releases"),
  and the `Share/README.md` release-history list (**trim the oldest bullet - the prose says
  "the fourteen most recent" and it silently drifts**). `tools/ds_share_sync.py` does NOT
  rewrite changelog history, so `--check` reads GREEN while public history loses a release.
- **Bump by QUOTED literal only**, never by bare string: `.md` prose mentions of an old
  version are historical MEASUREMENT CITATIONS and rewriting them falsifies the record.
  Exclude `.claude` AND `docs/_archive`. Last session: **254 files**. The
  `docs/DAEMON_SLAYER.md` banner is a bare-prose EXCEPTION and must be hand-edited.
- **`ROADMAP.md` is at 80437 bytes against an 81920 ceiling - 1483 bytes of headroom.**
  Any new NOW row or long closure note MUST relocate prose to `docs/ROADMAP_HISTORY.md` in
  the same commit, or `tests/test_doc_size_budget.py` fails.
- **Measure a normalizer's FALSE-POSITIVE side before shipping it.** The naive alias fold
  would have collapsed `223069` Void Immolation onto `443069` Hamstringer and suppressed
  **84 legal Arena purchases** - a worse bug than the one being fixed, in a mode the
  original defect never touched. Memory: `feedback_normalizer_check_false_positive_side`.
- **Re-run the Share sync AFTER any late test edit**, and do not run it while a suite is
  mid-flight (it rewrites 488 files under `Share/src`). Cost of getting this wrong: one
  full 20-minute re-run.
- **Exit code is NOT ground truth.** Redirect pytest to a FILE and read the summary line.
  A `tests/` run takes **~20 minutes** - launch it in the background and do docs work while
  it runs, then re-run it FRESH after any late edit.
- **A NEW-TEST-IN-THE-MIRROR TRAP:** any new test under `agents/daemon_slayer/tests/` that
  imports a HOST package (`core.*`) at module level MUST be added to `_HOST_DEPENDENT_TESTS`
  in `tools/ds_share_sync.py`.
- **Build-order tables: THREE families across TWO keyspaces; a bump needs ALL of them:**
  ```
  python tools/daemon_slayer_build_orders_generate.py --mode all
  python core/build_order_precompute.py --mode all --champions all
  ```
  Family A takes ~190s and prints; the precompute writes **silently with exit 0 and zero
  stdout** - confirm via `git status data/`. **Then CORROBORATE movement (or its absence)
  with a stamp-stripped payload diff** (drop `engine_version` / `generated_at` / `version`,
  then compare per champion). A numstat is NOT proof on a single-line JSON file.
- **ENGINE bump ritual: bump -> RESTART `:8893` -> VERIFY `/health` reads the NEW version
  -> regen -> measure.** Restart in **PowerShell**:
  `Stop-ScheduledTask -TaskName "RC-DaemonSlayer"; Start-ScheduledTask -TaskName "RC-DaemonSlayer"`
  (Git Bash mangles `/F` and `/Run` into paths).
- **`git apply` of a worktree diff FAILS in this repo.** Merge a slice by extracting its
  committed blobs: `git -C <worktree> show HEAD:<path> > <path>`. **Extract only the source
  paths - a precommit hook auto-syncs `Share/` into agent commits; let your own Share regen
  handle the mirror.** Two of four agents again reported ~500 phantom staged deletions in
  their worktree index after committing; both commits were intact. **Check
  `git show --stat HEAD` after every commit**, and remove worktrees BEFORE committing from
  the main tree.
- **A plumb can SILENTLY SUPERSEDE a monkeypatch** (a call-time keyword overrides a
  `functools.partial` keyword). Test failures after a plumb are premise decay - repair the
  premise onto the shipped path, never the assertion.
- **Derive controls at RUNTIME from the registry**, never hardcode them. A hardcoded Quinn
  negative control silently decayed the moment 1.248.0 seeded her.
- **A default flip makes its own tests vacuous** (`feedback_default_flip_weakens_tests`).
- **Never probe at an empty item list.** That artifact has manufactured FIVE false headlines.
  Last session carried an explicit non-empty list on every probe and added none.
- **DS probe traps:** `POST /rank` IS the CARRY scorer (there is no `/rank-carry`) and
  silently ignores archetype kwargs - use `/rank-<archetype>` otherwise; body key is
  `items`, not `item_ids`; `top` defaults to 40; always pass explicit non-zero target stats.
  **DS is plain HTTP on `:8893`.**
- **"Never run an extract in the same commit as a table regen" is UNVERIFIED.** Do not
  design a slice around it. The sibling hazard - never `--force` a Meraki re-extract,
  because `latest` is mutable - IS confirmed at three independent sites.
- **`ability_staleness.json` lies.** Its baseline predates the `62e4a410` shape fix.

## OPEN, HELD FOR AN OPERATOR CALL

- **K'Sante Q Ntofo Strikes** at `bonus_armor_pct` 40 / `bonus_mr_pct` 40 - held OUT of
  `_resist_damage_coupling.py`. Promoting it is a valuation call, not a data question.
- **Two live-gated rows** in `docs/LIVE_GAME_GATED_SYNC.md`: **G2-44** (the carry-route
  `exclude_off_axis_items` default-ON flip - Twitch serves Lich Bane #7 today) and the
  A-39 boot-CC default-ON flip. Both are do-not-flip-blind.
- **The DEFAULT-OFF seams shipped 1.247.0-1.249.0 are all still OFF**, now including
  `apply_passive_aura_damage`. Flipping any is an operator valuation call, not a build task.

## EXPECT

Measure before/after for every item and report the delta honestly, **including "no
movement" - but PROVE a no-op came from the NEW code path** (a spy recording the kwargs it
received is the technique that keeps working; a stamp-stripped payload diff is the
technique for tables). Report the exact pass/fail counts you observed THIS run; never carry
a prior or subagent-reported count forward. Then `/done`, and hand over the next 5.

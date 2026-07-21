# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-21b - R150 CONQUEROR 8010 OFFENSE GRANT (gemini headless loop, cycle 2) - ENGINE 1.233.0

**Tier-2 engine run.** LEDGER 989. Pushed `774ed236..7dfa003b`. ENGINE 1.232.0 -> 1.233.0.
Slice merge `a7c5f9db`, engine-tail commit `7dfa003b` (267 files).

## What shipped

Rune 8010 Conqueror credited into the EXISTING `agents/daemon_slayer/_rune_offense_grants.py`
registry behind the EXISTING `apply_rune_offense_grants` seam. No new module, no new flag.
Magnitudes at the default 12 stacks: **AD 12.96 (L1) -> 28.8 (L18), AP 21.6 -> 48.0**.

## The directive was mostly wrong and the audit ran BEFORE any code

7 target runes named; 6 were not work. 8236 + 8233 already shipped in R145. **8138 Eyeball
Collection, 8136 Zombie Ward, 8120 Ghost Poro are NOT IN the 16.14.1 `runesReforged.json`
at all** (removed from the game). 8210 Transcendence is Ability-Haste-only, settled inert.
The feed path the directive cited does not exist (real one is
`data/meta_build/ddragon/16.14.1/runesReforged.json`), and the new module + new flag it
specified would have duplicated the shipped lane.

## An adversarial slice refuted MY OWN brief mid-run

I told the builder to mirror `enemy_runes.py:149` at 21.6 -> 48.0. That is correct ADAPTIVE
FORCE but **AF IS NOT AD** - the enemy lane uses AF as a raw damage proxy, never as a stat.
Riot converts 1 AF = 1 AP **or 0.6 AD**, so my brief would have inflated the AD column by
**1.667x**. Caught pre-merge, corrected in-slice. The 0.6 ratio is pinned by a property test
against the registry's OWN rows (`round(0.6 * ap) == ad` on all 7 stated values), not by an
asserted constant. Same refutation also forced the stack count to become a KNOB
(`_ASSUMED_CONQUEROR_STACKS` + per-call `conqueror_stacks`, clamped 0-12) per
`rune_procs.py:212`, and killed the enemy-lane precedent citation because max-stacks flips
from conservative (threat lens) to optimistic (self lens).

## Traps hit this run - read before the next DS bump

1. **THREE build-order generators, two keyspaces.** FLAT `data/daemon_slayer/<patch>/` <-
   `tools/daemon_slayer_build_orders_generate.py`; NESTED HZ-B
   `data/daemon_slayer/build_orders/<patch>/` <- `core.build_order_precompute`; variants <-
   `core.build_order_variants`. **The stamp tests read the NESTED ones.** All need
   `--champions all`. I regenerated the flat set first and stayed red.
2. **TWO changelogs.** `test_changelog_tracks_engine_version` reads
   `agents/daemon_slayer/CHANGELOG.md` (bare `X.Y.Z (date` format), NOT `Share/CHANGELOG.md`
   (`## X -> Y (date)`). I edited Share first and stayed red. Both need an entry.
3. **`data/rewind_history.db` is gitignored**, so `git worktree add` never copies it and 27
   db-backed tests SKIP in any worktree (plus 2 for absent 1440p HUD profiles). That is the
   whole of the 29-test "passed -> skipped" delta a worktree slice will report. Not a
   regression. Confirmed by the skip count returning to 23 on main.

## OWED - real finding, not absorbed silently

**The FLAT Arena build-order table on main is five engine versions stale** (last written by
`1f13188b` at ENGINE 1.228.0; engine is now 1.233.0). Regenerating it changes 365 lines of
item ids - a material change to live Arena recommendations. Proven NOT caused by this slice
(`apply_rune_offense_grants`/`rune_ids` appear in neither generator, so the entry is
unreachable from build-order generation) and proven deterministic (two consecutive regens
content-identical). The three flat tables were REVERTED rather than ride into an engine-bump
commit. **Needs its own slice with its own validation.**

## Loop health

Cycle 2 breached its 5400s deadline at 03:13:51 - build subagent ~60 min, verifier ~29 min.
Controller injected stall recovery and extended once; no STOP. Not a hang.
`ops/loop/control/blocker.txt` on disk is STALE R145 text - do not read it as current.

## Don't-redo

Offensive-rune sweep is CLOSED for the 16.14.1 feed. Every remaining offensive rune is a
dead id, an AH-only rune on a settled-inert axis, a move-speed rune, a proc-damage rune
already scored by the burst consumer, or 8232 Waterwalking (uptime-blocked, no positional
signal). A further pass needs a role/positional signal, not another sweep. Do NOT model
Conqueror at a fixed 12 stacks. Do NOT mirror `enemy_runes.py` magnitudes into a STAT
registry without the AF conversion.

---

# 2026-07-21a - R149 SHARE FOLDER OVERHAUL (gemini headless loop, cycle N) - docs only

**Tier-0/1 docs run, ENGINE-IMPACT NONE.** LEDGER 988. Pushed `d4070710..dfb509b8`.
`Share/` re-presented as an external product artifact across FOUR disjoint worktree
slices (Claude sole merger, `verifier` subagent gate before every merge).

## What shipped

- **README** - external product page: problem framing, at-a-glance / contents / docs
  tables, a **Data sources and credits** section (Riot Data Dragon, CommunityDragon,
  Meraki/lolstaticdata, LoL wiki + attribution notes), an honest **Limitations** block.
- **docs 01-05** - net -294 lines. `04` -285 (registries + kit axes -> two tables),
  `05` -81 (stale audit residue cut). `02` gained the missing 7th-scorer section
  (`onhit_dps.py`); `03` gained per-provider credits + two corrected facts.
- **CHANGELOG** - 2737 -> 1079 lines, **105/105 release entries + dates preserved**
  (verifier diffed the semver token sets independently; zero new range compression).
- **MANIFEST template** - `tools/ds_share_sync.py` `_manifest_body()` split out under
  TDD; the GENERATED file now carries a product intro, `## Package stamp`,
  `## Generated vs authored`, and `## Where to start`.

## The two things worth remembering

1. **`Share/MANIFEST.md` CANNOT be hand-edited.** `_stamp_manifest()` regenerates it
   wholesale and the pre-commit hook re-runs the sync, so a hand edit is silently
   reverted with no error. Change the template in `tools/ds_share_sync.py` instead.
   `--check` deliberately excludes MANIFEST, so this never fails CI - it just vanishes.
2. **The verifier gate caught three factual defects the slice agents missed in their
   own work:** stale suite counts (8866/339 -> 9054/349), a wrong standalone error
   count (170 -> 179), and a documented reproduction command that aborts at collection
   and runs ZERO tests without `--continue-on-collection-errors`. All fixed pre-push.

## Carry-forward

- New disclosure now IN the package: it does not run its own suite clean standalone
  (8677 passed / 108 failed / 179 errors) because 60 of 349 test files reach outside
  it; the other 289 pass clean (6666 / 1915 subtests). Closing that boundary gap is
  unclaimed work, not scheduled.
- The `gist_share_sync` post-commit index corruption fired in 3 of 4 worktrees (up to
  4748 phantom deletions). Every agent caught it via `git show --stat` + plain
  `git reset`. Nothing phantom entered a commit. Guard still needed on every run.

Gates: `ds_share_sync --check` green (1.232.0, 501 files), RC **12470 passed**,
DS **9054 passed / 3582 subtests**, `ruff check .` clean.

---

# 2026-07-20p - LIVE-GATED DRAIN, operator present, 4 games - 6 rows closed, 9 new bugs

**Tier-1 RC-side. The one Tier-2 slice is parked on branch `ds/g2-12-ranged-reflect`
(`6fe6df12`), NOT on main.** LEDGER 987. Full detail: the dated drain block now at the
TOP of `docs/LIVE_GAME_GATED_SYNC.md` (that block is the real hand-off; this is the
summary).

Games: practice SR q3140 -> ARAM Mayhem q2400 -> Arena q1750 -> real SR draft q400.

## Closed (6): G1-00, G6-02, G2-18, G2-29, G2-34, G2-35

- **G1-00** - CHECK 1 across ALL FOUR champ-select shapes; CHECK 2 `champ_select`
  **BYTE-IDENTICAL** flag-ON vs OFF in the same lobby. Divergence was TWO keys
  (`config` AND `lcu_port`), not the one predicted. Adjudicated AGAINST the doc's
  premise - live `config.auto_accept` was `false`, so carry it, never synthesize.
- **G6-02** - first GATE 6 row ever closed. Ctrl+Shift+A with League foreground:
  PASSIVE -> ACTIVE + the 20s auto-revert, with listener receipts.
- **G2-18/29/34/35** - operator rulings + measurements; see the drain block.

## The 5 fixes sitting on main, UNCOMMITTED at time of writing -> now committed

ARAM balance resolver (dead in EVERY ARAM, fixed + live-verified in-game), auto-PGR
arm (= G4-26, root-caused to a 5s TTL vs a documented 8-11s capture lag), minimap
clear-on-exit, KP live value, champ-select mastery/meta placeholders.

## DO NOT REDO / carry-forward

- **G2-12 is decided, not open**: operator ruled the Thornmail reflect credit TOO HIGH
  (+8.963 pct measured, control byte-identical). The ranged-exposure fix is BUILT and
  DS-green on the branch. What is owed is the Tier-2 ritual: ENGINE bump, Share resync
  in the SAME commit, dual suite, `:8893` restart, LEDGER + doc update. **Open question
  the operator raised live: ARAM is a permanent teamfight, so the factor may need to be
  MODE-AWARE rather than a global 0.35.**
- **G2-18's residual is a code slice, not a game**: wire the live HP feed and delete the
  0.35 midpoint. RC already emits hp/hp_max (item 639).
- **G5-01 is THREE questions now** - augments WORK, anvils FAIL, rows are CORRUPT. Do not
  re-file it as one row. The anvil failure is most likely the 23-30s vision cadence, not
  a wiring gap.
- **Do NOT re-run the "is the ingest rail broken" investigation** - it is HEALTHY
  (2964 -> 2965, Arena game ingested). The 12-day gap was ARAM Mayhem + customs, operator
  confirmed. What remains is a rendering defect (`Unknown / 0-0-0`).
- `coaches/arena_coach.py` work from a CANCELLED agent is preserved as
  `CANCELLED_arena_coach.patch` in the session scratchpad - the tree was reverted, not
  shipped.

## Process lessons worth keeping

1. **Editing any `web/js/*` file hot-reloads every connected client mid-game** (ADR-008).
   This contaminated one of my own "clean reproduction" claims and probably caused an
   overlay-stranded-on-dashboard incident I first reported as spontaneous. Do not run
   web-touching agents while the operator is in a game they care about.
2. **pytest writes into `logs/hotkey_listener.log`** - a test monkeypatches the signal
   path to `Z:/nonexistent/...`. It produced two false readings during triage tonight.
3. **`zoom` re-captures the screen live** rather than cropping the previous screenshot -
   do not use it to inspect a frame that has already moved on.
4. I was WRONG four times and each correction changed the answer: the auto-PGR feed
   hypothesis (there IS a writer), "round counter stuck" (it RESETS), "re-trigger dead"
   (it fires), and an "independent reproduction" that was actually an overlay-shell
   client the router pins by design. Re-probe before asserting.

## NEXT SESSION = GEMINI HEADLESS LOOP (operator, 2026-07-20 end of session)

The next session CONTINUES the gemini headless loop, NOT the UI/UX pass below.

**The UI/UX work is OPERATOR-PRESENT and cannot run headless.** Its core is the
advocate-round loop where the operator rules element by element and explicitly wants
pushback - a Gemini-directed autonomous cycle has nobody to argue with, and item (2)
below ("offer 2-3 layout alternatives to choose between") is a decision request by
construction. Do NOT let a headless cycle "do the UI pass" and close it.

**What a headless cycle CAN legitimately build for it** (all non-interactive, and it
unblocks the operator-present session):
- the **dev display data** for the out-of-game pages (fixtures that make Home / PGR /
  Session / History / Replay / User Builds / Build Insights / Settings render fully
  populated with no live game),
- the **pseudo-screen for the in-game overlay** (a fixture harness that renders the HUD
  surface at 2560x1440 without League running),
- the **.rofl backfill** in section C of the queue doc (mechanical, testable, no
  operator judgement needed),
- any of the ~20 already-diagnosed defects in section B that are one-liners with a
  clear correct answer (e.g. the "Legion-PC" footer, the dangling no-data dots, the
  Replay table clipping) - but NOT the theme/layout/content questions.

## QUEUED (operator-present, run when he is at the keyboard) - UI/UX

**Queue doc: `docs/qa/UI_UX_QUEUE_2026-07-21.md`** - written at the end of this session,
carries the operator's own framing plus ~20 concrete defects measured live tonight. Read
it first; this is the summary.

Build **dev display data for the out-of-game pages** + a **pseudo-screen for the in-game
overlay** so UI work stops depending on catching a live game in the right state.

Operator's three asks, in his framing:
1. **Colour is off for RC as a whole**, out-of-game AND in-game - some pairs mix well,
   others read optically wrong, and **some panels do not match the rest thematically**.
   He wants a **theme swap explored**, not per-cell patching.
2. **2-3 LAYOUT ALTERNATIVES per page** to choose between, not one proposal to approve.
3. **Daily-use data points are redundant or lacking** - a content audit, not styling.
4. His own note: the earlier per-page UI reviews were **never finished** (larger issues
   kept interrupting). Treat the E11 sweep as INCOMPLETE.

**DO NOT close (1) by citing the old palette pass.** Memory
`feedback_operator_ui_qa_method` says E11 out-of-game is done for palette - that was a
COMPLIANCE hunt (bare hex vs tokens) and comes back near-empty. The operator is asking
about OPTICAL RESULT and CROSS-PANEL COHERENCE, which that pass never asked. Explicitly
re-opened by him.

**Highest-leverage content fix, and it needs no API:** the `Unknown / 0-0-0` rows are
backfillable from the local `.rofl` archive. `RC-RoflArchive` runs every 15 min into
`C:\Users\Administrator\Documents\RC_ROFL_Archive` and was VERIFIED working tonight - it
captured the SR, the Arena AND the q2400 ARAM Mayhem game that Match-V5 will never
return. Layer-1 extraction gives 365-367 fields x 10 players, no client, no patch gate.
Traps: join on participant ORDER never puuid, and sidecars carry no queue_id.

Method: the operator's own per-page loop (MAP -> ADVOCATE ROUNDS with counter-arguments,
he wants pushback -> ACT behind a verifier gate + the 5-phase fixture audit). One
cross-page design-system pass FIRST, or every page re-litigates the same colours.

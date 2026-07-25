# Riot Commander - next session: build the NEXT 5 open non-gated items

## CONTEXT (do not re-derive)

- HEAD `3ad4d075`, ENGINE **1.246.0**, patch 16.14.1, DS `agents/daemon_slayer/tests`
  **9471** / RC `tests/` **13061**. Tree clean, pushed. DS `:8893` live serving 1.246.0.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.246.0 +
  `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` (rows A-01e / A-04-3131 / A-26 / A-40(3) now
  SHIPPED; **A-15 REFUTED**).
- `ROADMAP.md` is **77834 bytes / 4086 headroom** against the 81920 limit
  (`tests/test_doc_size_budget.py`). Terse status flips only; narrative goes in
  `docs/LEDGER.md` (unbudgeted) + the DS CHANGELOG. Do NOT relocate the "DS per-champion
  meta-valuation sweep" section - it carries load-bearing PROBE HAZARD text.
- Last session ran 5 rows. **THREE filings were wrong in whole or part** and probe-first
  caught all three. Running total across two sessions: **6 mis-files caught before code.**

## METHOD (standing directive - this is a LOOP)

Five open **non-gated** items per session. Probe every row to PROBED before building:
grep the cited symbol, hit the live route, read the spec. Build as parallel worktree
agents on **disjoint file sets**, with you as **sole merger** holding every shared seam:
`ENGINE_VERSION`, both CHANGELOGs, **all three table regens across BOTH keyspaces**,
Share sync, living docs. Then `/done` + the next prompt.

**Operator decisions do NOT block.** When a row needs a default-ON/OFF or scope call,
dispatch a **self-adjudicating agent with scope to decide**, and require the evidence it
decided on, not just the verdict.

**Grep `docs/specs/**` and `tests/**` for every cited id/symbol BEFORE touching
implementation code.** That step has now caught 6 mis-files in two sessions.

**When open non-gated items run dry, roll this queue:** DS sweep -> UI/UX -> repo /
structure / security -> future-backlog -> research.

## BUILD THESE 5

### 1. A-27 / RM-114 NEXT BUY gold feed. **PROBED - cite corrected, root cause found.**
The row cites `core/item_advisor.resolve_build`; the real path is **`item_advisor.py:331`
at the REPO ROOT** (`core/item_advisor.py` does not exist). Root cause measured this
session: `resolve_build` early-returns `[]` on `if champion not in CHAMPION_BUILDS`, and
**`CHAMPION_BUILDS` is a hardcoded 6-entry dict** - exactly `['Caitlyn', 'Jinx',
'Miss Fortune', 'Nilah', 'Tristana', 'Vayne']` (the operator's own pool). Meanwhile DS
serves 173 champions with real build orders. So the widget is dark for 167 of 173.
The fix is to fall back to the DS build-order tables when `CHAMPION_BUILDS` misses, NOT
to hand-author 167 more dict entries. Check `data/daemon_slayer/16.14.1/build_orders_sr.json`
and `core/build_order.py` for the right seam. Watch the two-keyspace hazard below.
Files: `item_advisor.py` + tests.

### 2. A-18 / RM-87 intra-pool `ds.ehp` weighting (Ornn / Rammus).
Filed: resists pay twice while a self-EHP objective counts them once. Verify that claim
against the actual `ds.ehp` scorer before building - derive the double-count from source,
do not take the row's word for it (`feedback_reproduce_formula_from_source`: a cited
file:line is not a correct claim). If the double-count is real, the fix is an objective
shape change, so expect it to be Tier-2 and to move tank builds - measure which.

### 3. A-31 / BACKLOG R67 Terminus Light-side caster resists. **PROBED.**
`agents/daemon_slayer/_effects_data.py:611` is SR `3302`; the comment at **`:626`** says
"(_passive_resist_overrides.py is champion-keyed only); FUTURE" - that is the actual
blocker, and it is an ITEM-keyed vs CHAMPION-keyed schema mismatch, not a missing number.
The Arena mirror `223302` is at `:4437` and its note (`:4449`) already states "Light
caster-side resists not modeled". Per doctrine B the mirror carries a DIFFERENT magnitude
(Arena feed 8%/stack vs SR 10%/stack) - source each from its OWN feed, do not inherit.
Files: `_effects_data.py` + `_passive_resist_overrides.py` + tests.

### 4. A-11 / RM-44 Amumu magic-tank AP rush.
First tank gap: an axis-neutral EHP scorer structurally cannot value an AP damage item,
so his highest-WR Abyssal Mask is buried. Probe `/rank-tank` (NOT `/rank`) with explicit
target stats before accepting the filing. **Beware the RM-40/45/47 precedent** (ROADMAP,
measured 2026-07-24): a GAP champion and its own REFUTE control came back indistinguishable
to the scorer, which made the whole cluster unfalsifiable and BLOCKED. Pick a control
champion FIRST and check it is separable, before building anything.

### 5. A-30 / BACKLOG R129 bruiser-hybrid ability-DPS XOR. **Spec exists - READ IT FIRST.**
`docs/specs/leap/LEAP-06-r129-viego-hybrid-xor.md`, Sub-fix B (`:37`). Sub-fix A already
shipped at ENGINE 1.245.0 (`apply_cdragon_surplus_ad`), so only B remains. `hybrid.py`
scores damage as a strict XOR - AD-axis champs score on AUTO DPS only and their non-zero
ability damage is discarded. **Note the interaction:** `apply_ad_axis_ability_damage`
(RM-39 L2, ENGINE 1.223.0) already credits PHYSICAL+TRUE on the AD axis DEFAULT-OFF, so
establish what B adds ON TOP of that seam before building, or you will re-ship it.

## DO NOT PICK

- **A-25 / RM-94 Mejai's snowball stacks - ALREADY SHIPPED, row is stale.** I probed this
  while writing this prompt: the row says "`_effects_data.py:3257` pins Mejai's at +125 AP"
  but the live value is **`bonus_ap_stacked=25.0` at `_effects_data.py:3355`**, fixed at
  ENGINE 1.243.0. Close the row; do not rebuild. (Note `:2649-2655` is a DIFFERENT item
  at `bonus_ap_stacked=175.0` - an Arena per-round item, deliberate, leave it.)
- **A-15 / RM-80 Master Yi - REFUTED + CLOSED 2026-07-25.** `ds.onhit` is the on-hit-**AP**
  scorer (`core/ds_onhit_ap_roster.json` = Gwen/Kayle/KogMaw only); Yi is pure AD.
  44 bruisers enumerated, 11 probed, 0 moved. Do not re-open.
- **A-24 / RM-93 support-quest candidacy - REFUTED + CLOSED.** Deny is deliberate and
  test-pinned (`test_sr_quest_line_deny_rm93.py`).
- **A-14 / RM-79 + RM-95b Locke / Zaahen ability data - BLOCKED UPSTREAM.** Both are
  absent from Meraki's 171-champ bulk map. 95a closed 2026-07-25; do NOT try to synthesize
  their kits.
- **RM-92 ability-haste residual** - SIZED, verdict DEFER (`docs/specs/SCOPE_rm92_ability_haste.md`).
- **RM-40 / RM-45 / RM-47 mage cluster** - MEASURED BLOCKED on a scorer prerequisite.
- **`RC_VISION_MERGE_STRICT` default-ON** - LIVE-GATED, not headless-drainable.
- **A-09 / RM-36+RM-38 AD-caster pool** - A-01 already MEASURED un-filtering as necessary
  and NOT sufficient (108 -> 112, ZERO top-8 changes). Residual is RM-86 scorer kit-blindness.

## HAZARDS carried forward

- **NEW, cost 3 test failures last session: an ENGINE bump needs THREE doc sites the
  in-repo CHANGELOG does not cover.** `docs/DAEMON_SLAYER.md` status banner,
  `Share/CHANGELOG.md` (`## <prev> -> <new> (YYYY-MM-DD)` at the top of "Recent releases"),
  and the `Share/README.md` release-history list. **`tools/ds_share_sync.py` deliberately
  does NOT rewrite changelog history, so `--check` reads GREEN while the public history
  silently loses a release** - only `tests/test_ds_share_changelog_freshness.py` catches it.
- **NEW: the harness reported exit code 0 on a `tests/` run whose own summary said
  `3 failed`.** Exit code is NOT ground truth. Redirect pytest to a file and read the
  summary line; the first run's output file held nothing but a logging tail.
- **Build-order tables: THREE families across TWO keyspaces; a bump needs ALL of them:**
  ```
  python tools/daemon_slayer_build_orders_generate.py --mode all        (--mode, NOT --champions)
  python -m core.build_order_precompute --static --mode all --champions all
  python -m core.build_order_variants   --static --mode all --champions all
  ```
  Families B and C write **silently with exit 0 and zero stdout** - confirm via
  `git status data/`, not stdout. (Confirmed again this session.) A stamp-only diff across
  all 9 files is the honest way to CORROBORATE a "no movement" claim instead of taking it
  on report - that is what happened this session.
- **ENGINE bump ritual: bump -> RESTART `:8893` -> VERIFY `/health` reads the NEW version
  -> regen -> measure.** Restart via `taskkill /F /PID <pid>; schtasks /Run /TN
  "RC-DaemonSlayer"` in **PowerShell** (Git Bash mangles `/F` and `/Run` into paths). Get
  the pid with `Get-NetTCPConnection -LocalPort 8893 -State Listen`.
- **Bump by quoted-literal replace and EXCLUDE `.claude`** - live agent worktrees are full
  repo copies. True in-repo + Share count was **253** files this session.
- **Run `tools/ds_share_sync.py` AFTER writing the in-repo CHANGELOG**, never before.
- **Check `git show --stat HEAD` for unintended staged deletions after every commit** (the
  precommit hook runs its own sync). Zero deletions this session - keep verifying.
- **A default flip makes its own tests vacuous** (`feedback_default_flip_weakens_tests`).
  Pins for a now-default value must derive it from the feed, and a mutation check must show
  real failures.
- **Do not anchor a magnitude measurement on the engine still recommending the item you are
  demoting**, and **never probe at an empty item list** - that artifact has manufactured
  false headlines three times.
- **DS probe traps:** `POST /rank` is the CARRY scorer and silently ignores
  `enemy_ad_share`/`enemy_ap_share` (use `/rank-<archetype>`; there is NO `/rank-hybrid` -
  bruisers use `/rank-bruiser`); body key is `items` not `item_ids`; `top` defaults to 40;
  always pass explicit target stats (route defaults are 0.0 and a zero-HP target nullifies
  every percent-max-HP effect). **DS is plain HTTP on `:8893` - HTTPS returns curl exit 35.**
  In-process, `rank_items(snapshot, champion_id, level, ...)` needs `DataSnapshot.load()`
  as its first positional and returns a `RankResult` whose rows are under **`.ranked`**
  (it is not iterable).
- **NEW: map ids are not what you assume.** ARAM is map **12**; map **21 is Nexus Blitz**
  (I got this wrong this session and a build agent corrected me). `MODE_MAP_ID` wires only
  `{SR:11, ARAM:12, ARENA:30, BRAWL:35}`, so anything map-21-only is pool-illegal in every
  shipped mode. Verify a map id by listing its exclusive item pool before trusting it.
- **Deny/sibling sweeps go by ID SUFFIX across every map, never by name.** `3172` Gunmetal
  Greaves and `223172` Zephyr are DIFFERENT items. Meraki `rank: DISTRIBUTED` is NOT a
  pollution test.
- `tools/ds_feed_index.py` `KNOWN_STAMP_LAG` is NOT what its guard test reads - edit the
  `.py`, then run `python tools/ds_feed_index.py --write`.
- Never re-run `tools/daemon_slayer_extract.py` in the same commit as a table regen.
- **CLAUDE.md's "20,190 tests" is stale** against the measured `tests/` count (13061).
  Correct it at the next docs sync, not inline.

## EXPECT

Measure before/after for every item and report the delta honestly, **including "no
movement" - but PROVE a no-op came from the NEW code path** (a spy recording the kwargs it
received is the technique that keeps working). Report the exact pass/fail counts you
observed THIS run; never carry a prior or subagent-reported count forward. Then `/done`,
and hand over the next 5.

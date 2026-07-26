# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-26a - RM-115 CLOSED, and the last four pairs are declines (ENGINE 1.254.0)

ENGINE **1.253.0 -> 1.254.0**, patch 16.14.1. Two read-only spec agents in
parallel over the eight tail routes, then the wiring applied in the main thread
(one file - worktrees would only have made merge work). One build agent wrote
the acceptance test. Tier-2 in ritual order: bump by quoted literal (126 files /
154 occurrences) -> :8893 restarted -> `/health` re-read **1.254.0 BEFORE the
regen** -> both build-order families across both keyspaces -> Share sync (492
files, `--check` green) -> all four ENGINE doc sites **plus the two Share
release notes `--check` cannot see**.

Suites, both measured fresh AFTER the last edit:
**DS 9746 passed / 1 skipped / 4653 subtests.**
**RC `tests/` 13110 passed / 106 skipped / 460 subtests.**

## The headline is the DECLINE, not the drain

**Per-route stranded debt 25 -> 4. Name-collapsed 12 -> 2.** 21 pairs wired
across six client functions (`/burst` 7, `/dps` 6, `/rank-assassin` 4, `/rank`
2, `/ability-dps` 1, `/rank-mage` 1).

The session prompt framed `/beam` and `/v2/fight-report` as "a design call, not
wiring". The answer is **DECLINE for both**, and that is the durable output of
this session:

- `/v2/fight-report` has **ZERO callers repo-wide** - the literal appears only
  in its own docstring, the dispatch table, `docs/DAEMON_SLAYER.md`, the
  CHANGELOG and the two ledgers, and both of its tests call
  `compute_fight_report` in process. Served, never requested.
- `/beam` has ONE live consumer, `coaches/sr_draft_profile.py`, which holds its
  own HTTP call for reasons a migration must break: a 4.0s budget against this
  client's deliberate 0.5s `DEFAULT_TIMEOUT` fail-silent contract, and a
  two-value error channel that `_post_json`'s None collapses. And the seam is
  **arithmetically inert** for it - `mode="SR"`, and no champion carries an
  `sr` key in `wiki_stats.json`.

**The ledger's honest end state is 4, not 0.** Both declines carry an inline
re-open condition. A future session that reads 4 as debt and wires it will
re-introduce the exact reachable-and-dead illusion RM-115 existed to kill.

## What generalises

**The transport trap fired a third time, on a NEW key.** `/burst` parses
`runes` - **NOT** the EHP family's `rune_ids` - plus `caster_current_hp_pct`.
Neither is seam-prefixed, so neither guard sees them, and without them BOTH
`gate_*` seams are reachable-and-dead (measured byte-identical with `runes`
omitted). Same concept, different key per route: the 1.253.0 wiring did not
carry over.

**The gates are HONESTY gates and the direction inverts.** OFF applies the rune
amp unconditionally, so turning `gate_target_hp_amp` ON against a full-HP target
correctly REMOVES Coup de Grace's amp (716.343 -> 663.281). A test asserting
"ON is bigger" would have been wrong.

**Two silent traps on `/rank-assassin`, one of them the client's own default.**
`assume_squishy_target` is disabled by any positive `target_armor`
(`burst.py:2018`); the Collector arm of `assume_takedown` is disabled by
`target_max_hp=0.0` (`burst.py:1075`), which IS `rank_assassin_for`'s default -
so the seam reads half-working rather than misconfigured.

**`top` is a load-bearing transport.** `exclude_off_axis_items` REMOVES rows
rather than reordering them, and on an auto-attack scorer every removed row is
deep: Jhin is byte-identical at the client default `top=8` and only moves at
`top=200`.

**`apply_mode_modifiers` on `/rank` has two lanes and only one can reorder** -
the URF multiplier lane scales uniformly (Jhin top row x1.01, all 214 rows hold
order); the ar/swift addend lane does reorder.

## Judgement calls worth knowing about

- **`assume_magic_burst` was NOT deleted**, against the spec's recommendation.
  The route is right and the client is wrong, but the parameter is load-bearing
  across `archetype_dispatch`, `routes_state` and four test files. Resolved by
  making the lever reachable on the route that DOES parse it,
  `burst_for(assume_magic_burst=...)`, and filing the dead one.
- **One pre-existing test broke and was re-expressed, not relaxed.**
  `tests/test_ds_client_conversion_seam_plumb_w2.py` asserted the two W2 seams
  are the FINAL TWO parameters of `rank_for` - stricter than the convention its
  own docstring cites, and false for any correct append. Replaced with the
  property the convention actually protects (only the three genuine inputs may
  lack a default; both seams KEYWORD_ONLY with defaults; both after `timeout`;
  relative order preserved), which is strictly stronger.
- **The committed `build_order_variants_*` tables were STALE.** Six of nine
  tables are byte-identical after stamp-stripping; the three variants tables
  moved. Proven NOT attributable to this change by regenerating against the
  PRE-change client and getting byte-identical output to the post-change client,
  with both differing from the committed table.

## Filed, not fixed (each has real blast radius)

1. The dead `rank_assassin_for(assume_magic_burst=...)` parameter.
2. `rank_for` likewise emits `assume_passive_as_stacks` and `apply_target_vuln`
   into a `/rank` body that never parses them.
3. `rank_for_primary_archetype` has no pass-through for the 21 new kwargs, so no
   live coach tick can flip one yet. All 21 are DEFAULT-OFF, so nothing regresses.

## Ops note

`Get-NetTCPConnection -LocalPort 8893` matches lingering **TimeWait** sockets
(`OwningProcess = 0`), which reads as "port still bound" when DS is fully down -
and `taskkill /F /PID 0` fails as a critical system process. Filter on
`-State Listen`. Memory updated.

---

# 2026-07-25j - the EHP-family block drained, and the transports nobody was counting (ENGINE 1.253.0)

ENGINE **1.252.0 -> 1.253.0**, patch 16.14.1. Operator-directed ("drain the
EHP-family block next"). Four read-only probe agents in parallel gathered
acceptance evidence for all 20 seams against live :8893; the wiring itself is
ONE file, so it was applied in the main thread. Tier-2 in ritual order: bump by
quoted literal (132 files / 153 occurrences) -> :8893 restarted -> `/health`
re-read **1.253.0 BEFORE the regen** -> both build-order families across both
keyspaces -> Share sync (492 files, `--check` green) -> all four ENGINE doc
sites.

Suites, both measured fresh AFTER the last edit:
**DS 9721 passed / 1 skipped / 4653 subtests.**
**RC `tests/` 13110 passed / 106 skipped / 460 subtests.**

## The headline

**Per-route stranded debt 101 -> 25. Name-collapsed 33 -> 12.** Twenty seams
shared by `/ehp`, `/hybrid`, `/rank-tank` and `/rank-bruiser` (17 on all four)
were engine- and route-complete but unreachable from the client: 76 of the 101
pairs.

Evidence standard, stated because it narrows the operator's one-control-per-seam
rule deliberately: REACHABILITY proven structurally for all 76 pairs by the
per-route guard (that is what it exists for); behavioural EFFECT proven ONCE per
seam on its most diagnostic route against a NAMED registry-proven control. 19
live cases through the real client.

## Two findings that outlive this block

**THREE STRANDED TRANSPORTS, and BOTH guards are blind to all three** because
none is seam-PREFIXED. `rune_ids` and `enemies` were parsed by all four routes
and sent by NO client function; `score_by` was missing from `rank_bruiser_for`.
EIGHT of the twenty seams consume one of them, so wiring the flags alone would
have made ~16 pairs reachable-and-DEAD - the exact illusion RM-115 exists to
kill, introduced by the fix for it. It surfaced only because the acceptance test
was written from MEASURED cases and failed with `TypeError: unexpected keyword
argument 'enemies'`. A test built from assumptions would have gone green.
**Any future drain must check the non-prefixed transports a seam consumes.**

**A defect I introduced and caught before shipping.** `apply_build_tenacity` is
TRI-STATE - `_route_rank_tank` (`server.py:701-703`) and `_route_rank_bruiser`
(`:973-975`) read it as None-when-absent and the engine defaults it ON under
`score_by="cc_blended"`. My first pass gave it the uniform `bool = False` +
emit-when-True treatment of the other nineteen, which cannot express False: an
OFF switch that could not turn anything off. Now `Optional[bool] = None`, with
an assertion that omitting the key reproduces the ON ordering. Confirmed it is
the ONLY tri-state seam by an AST scan of all four handlers, not by eye.

## Recorded so nobody rediscovers them

- **Three seams provably CANNOT reorder**: `apply_survival_window`,
  `apply_passive_revive`, and `apply_champion_tenacity` without
  `apply_build_tenacity`. Each is a uniform multiplier on the EHP numerator and
  a ratio sort key is invariant under uniform scale - Tryndamere's ratio is
  exactly 1.291666667 on all 138 rows, both sort keys. The "moved" rows for
  Zac/Anivia/K'Sante are 1e-12 ULP ties. Acceptance is the `/ehp` SCALAR; a rank
  criterion is unsatisfiable by construction.
- **`apply_mode_modifiers` is INERT on ARAM.** The ARAM axes apply
  unconditionally; the flag gates the wiki-sidecar lane, which excludes ARAM to
  avoid double-counting. URF is the mover. An ARAM case would look like a bug.
- **Seven companion gates**, each a false negative if missed - rune ids, a
  SHIELD for `apply_rune_hsp_amp`, level >= 7 for `assume_item_health_stacks`,
  `enemies` AND an unsaturated comp for the spell shields (five heavy-CC enemies
  pin `cc_pressure_fraction` at 1.0 and the clamp eats the seam), build tenacity
  for champion tenacity, and `target_max_hp` (NOT `target_hp`) for the AD axis.
- **One control shape is INVALID and the test asserts it**: a manaless champion
  is not a control for `apply_item_mana_health` - the item supplies its own mana
  (Garen 5099.337 -> 5242.948).

## Corrections to my own work

- I said `apply_mode_modifiers` is parsed by **SEVEN** routes, three times. It
  is **EIGHT**. Corrected in the live artifacts; LEDGER 1051 and the
  1.250.0/1.251.0 CHANGELOG entries are append-only and were left as written,
  with the correction recorded forward.
- The guard assertion pinning the per-route ledger at a FLOOR of 33 was
  disproved by this drain (25 vs the sibling's 12). The premise was wrong, not
  the number, so it was replaced with the inequality that holds BY
  CONSTRUCTION: a name stranded everywhere contributes at least one (route,
  seam) pair, so per-route total >= name-collapsed total, always.

## Still open

**25 pairs, and none is a shared block:** `/burst` 7, `/dps` 6,
`/rank-assassin` 4, `/v2/fight-report` 3, `/rank` 2, one each on
`/ability-dps`, `/rank-mage`, `/beam`. **`/beam` and `/v2/fight-report` have NO
client function at all** - those four pairs need one invented before any wiring.
The cheap shared-block phase of RM-115 is over; what remains is per-seam work.

Unchanged carry-forwards: RM-96 Zilean, `parse_leveling_bases` (35 labels across
31 of 90 blocks), B1's unregenerated `--full-roster` artifact, and the
`rank_assassin_for(assume_magic_burst=...)` dead parameter.

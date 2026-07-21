# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-21l - R161 ARENA STAT LINE DOCTRINE B (gemini headless loop, cycle 8) - ENGINE 1.237.0 -> 1.238.0

LEDGER 1002. Commit `77a34890`. ENGINE-IMPACT BUMP. DS bounced, both build-order families
regenerated, Share mirror re-synced. No RC restart needed (no route change).

## The decision

R152, R153 and R160 each surfaced the same question and each correctly refused to answer it: do
Arena mirrors inherit their SR twin's coefficients, or does an explicitly different DDragon stat
line win? The director answered **doctrine B - an explicit Arena stat line wins.** Arena mirrors no
longer inherit SR BASE STAT magnitudes. Passive-COEFFICIENT inheritance where Meraki has no mirror
entry is unchanged; only explicitly-stated base stat lines flip.

Twelve rows re-credited from their own DDragon 16.14.1 feed entry: lethality `223142` 18->22,
`223814` 15->14, `224004` 15->21, `226676` 10->12, `226699` 10->20, `226701` 18->15, `226691`
18->22 (inert, maps={}); flat magic pen `223020` 12->20, `224645` 15->10; percent pen `223036`
0.35->0.40, `226694` 0.35->0.40, `223302` Terminus 0.30->0.24 on both axes (8 percent per stack,
cap 3). SR twins untouched.

Highest live impact is the BOOT, not the lethality list: `223020` is the Arena mage default boot,
in essentially every Arena AP build, under-crediting magic damage ~5.7-6.9 percent through
`effective_target_mr`.

## Two directive premises were refuted before any code landed

1. The directive said to invert `test_arena_prowlers_lethality_same_as_sr`. `226693` Prowler's Claw
   states 22 in the Arena feed and SR `6693` states 22 - an exact match, never a divergence.
   Inverting it would have fabricated a failure. Kept; only its docstring reason changed.
2. "Meraki carries no 22xxxx/44xxxx mirror ids at all" (repeated in ORCHESTRATION_PLAN since R152)
   is FALSE - the pinned 16.13.1 snapshot carries 17. It just lacks `223302`, the only claim the
   Terminus guard needed. Both corrections are now fenced in the plan's don't-redo.

Doctrine B also was not novel: `226695` Arena Serpent's Fang has always credited its own 19 against
SR `6695` 15, and R152 said "do not normalize them". The call generalizes an existing exception.

## The bump was not the deliverable - the regen was

A bump alone leaves every precomputed Arena build order computed under the REJECTED doctrine. Both
families regenerated against the bounced 1.238.0 engine: **99 of 173 Arena build orders and 89 of
173 Arena variants moved.** Drift-guard held exactly as predicted - SR and ARAM differ only in
stamp fields (all 12 ids are map-30 only), so a non-stamp SR/ARAM diff would have meant a leak.
`reference_build_order_regen_full_roster_and_nightly` earned its keep twice: the WRONG-TOOL trap
(the `tools/` script is not what the stamp tests read) and the `--champions all` trap (omitting it
collapses 173 champs to a 10-champ seed).

## Incidental find - the flat table was ten engine versions stale

`data/daemon_slayer/16.14.1/build_orders_sr.json` picked up a `6696` -> `6695` flip in 6 SR cells
(Zed, Qiyana). Last written at ENGINE 1.228.0 (`1f13188b`); the nested table already carried `6695`
at 1.237.0, so the two disagreed before this cycle. The live deterministic + laning coaches had
been serving 1.228.0-era builds. Now current. Not caused by doctrine B.

## Gates

Verifier CONFIRM 8/8 on the merged tree. DS 9190 passed / 1 skipped / 3865 subtests. RC suite
green. ruff clean. `ds_share_sync --check` green at 1.238.0. Three worktree agents on disjoint file
sets (engine data / guard tests / docs), Claude sole merger, engine merged first and docs last.

---

# 2026-07-21k - R160 PERCENT-PENETRATION CATALOG PARITY (gemini headless loop, cycle 7) - ENGINE UNCHANGED 1.237.0

LEDGER 1001. Commit `d6d3fb3f`. ENGINE-IMPACT NONE - no math change, no production `.py` touched,
no `ENGINE_VERSION` bump, no DS bounce, no RC restart.

## What shipped

`agents/daemon_slayer/tests/test_pen_pct_catalog_r160.py` - a catalog-derived parity guard for the
PERCENT penetration axis. The directive asked for a pen sweep across percent armor pen, lethality
and magic pen; R152 had already closed lethality (31 exact-match, 0 absent) and R153 had already
closed FLAT magic pen with a permanent guard. The premise check found the one third nobody swept:
`armor_pen_pct` / `magic_pen_pct` had no catalog-derived test at all.

Three read-only agents on disjoint scopes - two catalog to registry, one running it BACKWARDS
(registry to catalog, the direction that catches a credited id the catalog dropped). All three
converged: **zero uncredited live ids on either axis.** 12 armor-pct swept (6 exact), 9 magic-pct
(7 exact), 16 credited rows, 0 stale. Every population was re-derived independently against both
catalog layouts before a single assertion was written.

## The three divergences are pinned, not fixed

- `223036` / `226694` state 40 percent in the Arena feed, registry credits their SR twins' 35.
- Terminus `3302` / `223302` state a PER-STACK value (10 SR, 8 Arena) vs a full-stack credited 0.30.
- `6632` / `226632` state 3 percent from dead mythic-template text but are unbuyable everywhere.

## The test failed first, and the failure was the finding

The draft asserted the flat and percent sweeps are disjoint by id. RED on `3175` Spellslinger's
Shoes, which states BOTH `18 Magic Penetration` and `8% Magic Penetration` on consecutive rows -
DS credits both axes correctly. They are disjoint by MAGNITUDE, never by id. Now pinned.

## Gates

Verifier CONFIRM 8/8 with live-object defect injection (baseline 0 failures; `3135` pen to 0.0
gives 2; `3036` to 0.99 gives 1; restored 0), and it caught a wrong docstring path fixed
pre-commit. DS 9190 passed / 1 skipped / 3865 subtests. Guard 17 / 28 subtests. ruff clean,
0 non-ASCII, zero production mutation. Share `--check` in sync 1.237.0 / 497 files.

## Carry-forward

The Arena-inheritance doctrine call is now 12 rows across three sweeps (R152 7 lethality, R153 2
flat magic pen, R160 2 percent armor pen + Terminus). Escalated to the director via PART C
`gemini_ask.txt` with both options and their blast radius. Do NOT reconcile any of those rows
without the answer - the guard will go red by design if someone tries.

---

# 2026-07-21j - R159 RUNE-OFFENSE SATURATION, REMAINING THREE TREES (gemini headless loop, cycle 6) - ENGINE UNCHANGED 1.237.0

LEDGER 1000. Merge `add6f26f` (slice `77d448af`). ENGINE-IMPACT NONE - no math change, no behavior
change, no `ENGINE_VERSION` bump. The default-OFF `apply_rune_offense_grants` path stays
byte-identical. No DS bounce, no RC restart: there is nothing to reload.

## What shipped

R158 closed Domination `8100` + Sorcery `8200` and recorded the carry-forward that Precision
`8000`, Resolve `8400` and Inspiration `8300` were still PROSE-ONLY. This closes them.
`_SATURATED_TREE_IDS` in `agents/daemon_slayer/tests/test_rune_offense_saturation_r158.py` is now
all five trees, so the module docstring's saturation claim is a thing CI can fail on rather than a
sentence. Coverage: 62 live runes = 5 registered (`8010`, `8233`, `8236`, `8316`, `9104`) + 57
adjudicated, up from 23, counted by a new test rather than eyeballed.

## The point of the slice is the two honest non-answers, not the 32 easy ones

A guard whose reasons are wrong is worse than no guard - it converts an unmeasured claim into a
green test. Two of the 34 new ids DO grant a real offensive stat, and both are recorded as blocked
gaps naming the blocker, following the `8232` Waterwalking precedent:

- **`8008` Lethal Tempo - ROLE-BLOCKED.** It grants stacking attack speed (6% melee / 4% ranged per
  stack to 6 stacks). The value is role-split and this seam takes no melee-or-ranged argument, AND
  that same bonus attack speed is already an INPUT to Lethal Tempo's own on-attack damage term in
  `rune_procs.py`. Crediting it here independently would DOUBLE-COUNT, not close a gap. The two
  lanes have to be wired together.
- **`8313` Triple Tonic - UPTIME-BLOCKED.** Its level-6 Elixir of Force grants 25 Adaptive Force,
  but for 60 seconds once, and this engine has no consumable-uptime anchor to spend that against.
  Its two siblings grant nothing offensive (Elixir of Avarice is gold plus minion-only true damage,
  Elixir of Skill is a skill point).

The other 32 are plain non-grants, each grounded in the rune's own DDragon `longDesc` and, where
applicable, an existing registration elsewhere: `8005`, `8014`, `8017`, `8299`, `8369`, `8437`,
`8439`, `8401` cite `rune_procs.py`; `8439`, `8429`, `8242` cite `_rune_resist_grants.py`; `8446`
Demolish and `8021` Fleet Footwork cite the explicit honest-exclusion notes already in
`rune_procs.py` (tower-only damage, and a heal whose AD/AP appear only as scaling INPUTS); `9105`
Legend: Haste and `8347` Cosmic Insight use the settled MEASURED-INERT ability-haste wording;
`8451` Overgrowth and `8345` Biscuit Delivery say health is not one of this registry's three
columns rather than falsely claiming no offensive stat.

## Verification

TDD RED recorded before the mapping landed: `2 failed, 9 passed, 52 subtests` -
`AssertionError: 28 != 62` on the new counting test, plus a 34-element diff naming every uncovered
id starting at `('8005', 'Precision/PressTheAttack')`.

Verifier subagent CONFIRM 8/8, re-running the DS suite itself rather than taking the slice's
numbers: `_ADJUDICATED_NON_GRANTS` resolved by AST `literal_eval` (57 keys, no silent dict-literal
collapse), `ENGINE_VERSION` diffed against main to prove it untouched, and - the claim that
mattered - the `longDesc` for `8008`, `8021`, `8299`, `9103`, `8451`, `8446` read out of the feed
and compared against each reason string to hunt for a false non-grant.

DS 9173 passed / 1 skipped / 3837 subtests (verifier's own fresh run, exit 0). ruff
`All checks passed!`. 0 non-ASCII bytes in both sources and both Share mirrors. Commit is exactly 5
files with 0 deletions. `test_no_adjudicated_id_credits_anything_on_its_own` grew to 114 subtests
(57 x 2), which is what proves the mapping inert on both an AD and an AP build. Share mirror +
`MANIFEST.md` restamp landed in the SAME commit via the precommit hook; `--check` in sync at
1.237.0 / 496 files.

The slice agent hit the known worktree-index corruption right after committing (~500 phantom staged
deletions). `git reset` repaired it; both the agent and the verifier re-confirmed the commit is
still the same 5 files with everything present on disk.

## Don't-redo

All five rune trees are now machine-guarded and the sweep is CLOSED. A future patch that adds a
stat rune will fail the guard by itself, so do NOT re-scan the feed for uncovered runes.

`8008` Lethal Tempo and `8313` Triple Tonic are KNOWN, RECORDED gaps with named blockers, not
oversights. Crediting Lethal Tempo needs the attack-speed lane wired to its existing `rune_procs.py`
damage term (double-count hazard); Triple Tonic needs a consumable-uptime anchor that does not
exist. Neither is a free win.

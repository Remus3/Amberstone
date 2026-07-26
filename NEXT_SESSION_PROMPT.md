# Riot Commander - next session: the RM-115 tail, or pick a new row

## CONTEXT (do not re-derive)

- ENGINE **1.252.0**, patch 16.14.1. Tree clean and pushed at `5f94f965`.
  DS `:8893` scheduled task is **Running** and `/health` reads 1.252.0.
- Suites measured fresh 2026-07-25 AFTER the last edit: DS **9702 passed / 1
  skipped / 4650 subtests**; RC `tests/` **13110 passed / 106 skipped / 460
  subtests**.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.251.0 + 1.252.0 +
  `docs/LEDGER.md` 1051 + 1052 + `ROADMAP.md` **RM-115**.
- ROADMAP is at **72185 of 81920 bytes** (9735 headroom).

## WHERE RM-115 STANDS

**All four filed priorities are SHIPPED** across 1.251.0 and 1.252.0:
`apply_ability_base_overrides` (gates 2+3), `apply_passive_aura_damage` (gate 3
plus an unfiled `/ability-dps` gate-2 half), `kit_conversion_strength` on
`/rank-assassin`, and `kit_conversion_strength` on `/rank-bruiser` via
`hybrid.py`. Do NOT re-plumb any of them.

**What remains is the tail the re-measurement exposed.** The filed "34 stranded"
collapsed reachability to a NAME; per `(route, seam)` it is **101**, and the
four shipped seams did not reduce that number (see the note on non-prefixed
seams below). Two guards exist and they are **not interchangeable**:

- `test_route_seams_reach_the_client.py` - name-collapsed, 33-entry ledger
- `test_route_seams_reach_the_client_per_route.py` - per (route, seam),
  101-entry ledger

**Do not treat either guard's green as evidence a specific route is wired**, and
note that a seam without an `apply_` / `assume_` / `gate_` / `exclude_` prefix -
`kit_conversion_strength` is the live example - appears in **NEITHER** ledger.
That is why both kit-conversion slices carried their own acceptance tests.

## OPTION 1: drain the EHP-family block (the largest remaining win)

`/ehp` (18), `/hybrid` (19), `/rank-tank` (19) and `/rank-bruiser` (20) share
essentially ONE seam block - `apply_item_resist_grants`,
`apply_passive_mitigation`, `apply_passive_resist`, `apply_rune_*`,
`assume_item_*`, `apply_survival_window`, ... - so a single client wiring pass
would likely clear most of the 101. `/beam` and `/v2/fight-report` have NO
client function at all.

**Do NOT wire all of them in one session.** Each seam needs its own
before/after with a NAMED byte-identical control, which is what has made every
one of these slices trustworthy. Pick a coherent sub-block (the rune lane, or
the item-resist lane), wire it across the routes that share it, and prove each.

## OPTION 2: pick a different row

- **RM-96 Zilean** - fully specced, unbuilt. Cast rate 0.00424, 15.9x below
  Soraka. **Trap:** seeding a factor off `ability_hps` MAGNITUDE gives a silent
  null - he is 4.66 vs Janna 5.06, only 8 pct apart. Only the CAST RATE
  separates him.
- **`parse_leveling_bases`** (`ds_wiki_staleness_check.py:188-196`) keeps only
  the first label pair per `{{st}}` block; 31 of 90 blocks in a 50-page sample
  carry two or more, dropping 35 Meraki-matching labels. So
  `ability_staleness.json` is a structural undercount, and
  `_ability_base_overrides`'s "exactly those six" scope derives from it - i.e.
  the six corrections shipped at 1.251.0 may not be the full set.
- **B1** shipped code with no regenerated data - `--full-roster` exists but no
  16.14.1 artifact was produced with it.
- **The dead client parameter.** `rank_assassin_for(assume_magic_burst=...)`
  can never take effect: `server.py:1971-1973` documents that
  `rank_items_by_burst` deliberately does not accept it (only
  `compute_burst_damage` does). The ROUTE is correct. Fix direction is a real
  choice - drop the parameter, or lift the engine kwarg - so decide before
  building. **Do not "fix" it by adding a route parse**; that was a probe's
  filing and it was wrong.

## DO NOT PICK

- **RM-44 / RM-91 / RM-90-S3** - premise REFUTED, the prerequisite shipped
  1.247.0.
- **RM-48 Azir** - BLOCKED-UNFALSIFIABLE.
- **A-32 kit-pen** - 3 of 4 mis-filed, the row names the wrong module.
- **RM-85 Nasus** - MIS-FILED, it was the `top=40` trap.
- Do not re-attempt A-21 S1 expecting table movement, and do not re-open the
  173/173 DS_SWEEP roster.

## HAZARDS

- **A pinned "signature tail" assertion is self-defeating under append-at-END,
  and it FIRED again at 1.252.0.** `test_rune_resist_signature_convention_r134.py`
  GUARD 1 breaks on every legitimate append. The correct response is the one its
  own docstring names: case the entry points separately and update the guard.
  **Never weaken the assertion.**
- **Row agreement is NOT evidence** - N rows citing one blocker is ONE
  unverified claim.
- **Reproduce a finding's ORIGINAL params before contradicting its numbers.**
  Two sessions running, an in-process figure differed from the live one purely
  because the route carries inputs the direct call did not (`enemy_ad_share`).
  Quote the live number when you claim a live measurement.
- `/rank*` returns `item_id` as a **STRING**; default `top` is 40; `items=[]`
  under-ranks amp/complementary items; `POST /rank` is the CARRY scorer and
  there is no `/rank-hybrid`.
- Any new DS test importing `core.*` at module level must be registered in
  `tools/ds_share_sync._HOST_DEPENDENT_TESTS` - **warn every build agent, not
  one.**
- Four doc sites on a bump; keep the Share README at **fourteen** bullets; an
  ENGINE bump also requires a PREPENDED `agents/daemon_slayer/CHANGELOG.md`
  entry or `test_changelog_tracks_engine_version.py` fails.
- Exit code is not ground truth - redirect pytest to a file. **The RC suite
  takes ~20 minutes and exceeds the foreground tool timeout; run it in the
  background.**
- If a slice's edits all land in the same one or two files, do NOT spawn
  worktree agents - that is false parallelism. Probe in parallel, wire in the
  main thread.

## START WITH

`/clear`, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log +
ROADMAP RM-115.

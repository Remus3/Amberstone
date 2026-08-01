# Riot Commander - next session: the RM-115 tail is per-seam now, or pick a new row

## CONTEXT (do not re-derive)

- ENGINE **1.253.0**, patch 16.14.1. Tree clean and pushed at `a7d54103`.
  DS `:8860` scheduled task is **Running** and `/health` reads 1.253.0.
- Suites measured fresh 2026-07-25 AFTER the last edit: DS **9721 passed / 1
  skipped / 4653 subtests**; RC `tests/` **13110 passed / 106 skipped / 460
  subtests**.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.251.0 / 1.252.0 / 1.253.0
  + `docs/LEDGER.md` 1051 / 1052 / 1053 + `ROADMAP.md` **RM-115**.
- ROADMAP is at **71321 of 81920 bytes** (10599 headroom).

## WHERE RM-115 STANDS

All four filed priorities SHIPPED (1.251.0, 1.252.0) and the EHP-family block
DRAINED (1.253.0). **Per-route debt 101 -> 25; name-collapsed 33 -> 12.**

**The cheap phase is over.** The 76 pairs closed at 1.253.0 were one shared
block across four routes. The remaining 25 have no shared structure:

| route | pairs | note |
|---|---|---|
| `/burst` | 7 | |
| `/dps` | 6 | |
| `/rank-assassin` | 4 | |
| `/v2/fight-report` | 3 | **NO client function exists** |
| `/rank` | 2 | |
| `/ability-dps`, `/rank-mage`, `/beam` | 1 each | `/beam` has **NO client function** |

`/beam` and `/v2/fight-report` need a client function invented before any of
their four pairs can be wired at all - that is a design decision, not a wiring
job. Decide whether those routes should have one before starting.

## READ THIS BEFORE WIRING ANY FURTHER SEAM

**Both reachability guards are blind to non-seam-PREFIXED transports, and this
has now bitten three times.** A seam can be wired, reachable, green on both
guards, and completely inert because the transport it consumes is missing:

- `rune_ids` and `enemies` were parsed by all four EHP-family routes and sent by
  NO client function. Eight seams consume them.
- `score_by` was missing from `rank_bruiser_for`.
- `kit_conversion_strength` (1.251.0 / 1.252.0) appears in neither ledger for
  the same reason.

**Before wiring a seam, read its consumer and list the non-prefixed body keys it
needs.** Then check the client sends them. Neither ledger will tell you.

Second standing trap: **check whether the seam is TRI-STATE.** `_opt_bool(body,
k, False) if k in body else None` means omitting the key inherits an engine
default that may be ON - a plain `bool = False` client kwarg then cannot express
OFF. `apply_build_tenacity` was the one instance in the last block; find them
with an AST scan for the `IfExp`-over-`in body` shape, not by eye.

Third: **some seams provably cannot reorder.** A uniform multiplier on the EHP
numerator leaves a ratio sort key invariant, so a rank-order acceptance
criterion is unsatisfiable by construction. `apply_survival_window`,
`apply_passive_revive` and `apply_champion_tenacity`-alone are the known cases;
their acceptance is the `/ehp` scalar. Check the consumer before promising a
rank swap.

## OPTION 2: pick a different row

- **RM-96 Zilean** - fully specced, unbuilt. Cast rate 0.00424, 15.9x below
  Soraka. **Trap:** seeding a factor off `ability_hps` MAGNITUDE gives a silent
  null - he is 4.66 vs Janna 5.06. Only the CAST RATE separates him.
- **`parse_leveling_bases`** (`ds_wiki_staleness_check.py:188-196`) keeps only
  the first label pair per `{{st}}` block; 31 of 90 blocks in a 50-page sample
  carry two or more, dropping 35 Meraki-matching labels. `ability_staleness.json`
  is therefore a structural undercount, and `_ability_base_overrides`'s "exactly
  those six" scope derives from it - so the six corrections shipped at 1.251.0
  may not be the full set.
- **B1** shipped code with no regenerated data - `--full-roster` exists but no
  16.14.1 artifact was produced with it.
- **The dead client parameter.** `rank_assassin_for(assume_magic_burst=...)` can
  never take effect: `server.py:1971-1973` documents that `rank_items_by_burst`
  deliberately does not accept it. The ROUTE is correct. Fix direction is a real
  choice - drop the parameter, or lift the engine kwarg. **Do not "fix" it by
  adding a route parse**; that was a probe's filing and it was wrong.

## DO NOT PICK

- **RM-44 / RM-91 / RM-90-S3** - premise REFUTED, prerequisite shipped 1.247.0.
- **RM-48 Azir** - BLOCKED-UNFALSIFIABLE.
- **A-32 kit-pen** - 3 of 4 mis-filed, the row names the wrong module.
- **RM-85 Nasus** - MIS-FILED, it was the `top=40` trap.
- Do not re-wire anything in the EHP-family block, the four ability routes, or
  `/rank-assassin`'s kit-conversion seam - all shipped 1.251.0-1.253.0.

## HAZARDS

- **A pinned "signature tail" assertion is self-defeating under append-at-END**
  and fired again at 1.252.0. The correct response is the one
  `test_rune_resist_signature_convention_r134.py`'s own docstring names: case
  the entry points separately and update the guard. **Never weaken it.**
- **Write acceptance tests from MEASURED cases, not assumed API shapes.** The
  `enemies` transport gap surfaced only because the test blew up with a
  TypeError; a test written from assumptions would have gone green over dead
  seams.
- **Controls must be registry-proven, not observed.** "It did not move" is not
  evidence. And check the control is VALID: a manaless champion is not a control
  for `apply_item_mana_health` because the item supplies its own mana.
- **Watch for saturation.** Five heavy-CC enemies pin `cc_pressure_fraction` at
  1.0 and the clamp swallows any CC-reducing seam entirely - reads as a clean
  negative.
- `/rank*` returns `item_id` as a **STRING**; default `top` is 40; `items=[]`
  under-ranks amp items; `POST /rank` is the CARRY scorer; there is no
  `/rank-hybrid`; `/rank-bruiser` parses `target_max_hp`/`target_bonus_hp`, NOT
  `target_hp`.
- Any new DS test importing `core.*` at module level must be registered in
  `tools/ds_share_sync._HOST_DEPENDENT_TESTS` - **warn every build agent.**
- Four doc sites on a bump; Share README stays at **fourteen** bullets; an
  ENGINE bump needs a PREPENDED `agents/daemon_slayer/CHANGELOG.md` entry or
  `test_changelog_tracks_engine_version.py` fails.
- Exit code is not ground truth - redirect pytest to a file. **The RC suite
  takes ~20 minutes and exceeds the foreground tool timeout; background it.**
- If a slice's edits land in one or two files, do NOT spawn worktree agents -
  that is false parallelism. Probe in parallel, wire in the main thread.

## START WITH

`/clear`, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log +
ROADMAP RM-115.

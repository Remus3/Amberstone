# Lane gated - run s133g009-ddc499 (session 133, cycle 9, 2026-10-25)

No game this window: League client open at home, no lobby, no champ select, no game.

```
IN-GAME  0 min                                   |  IDLE whole cycle (04:43 to about 05:25 local)
DRAINED  0 rows                                  (nothing the idle client state answers)
READY    1 row + 1 doc row: G3-14 (findings + CHECK), G5-05 CHECK B rewritten (RM-879 SHIPPED)
REFUTED  3 + 3 claims by two independent verifier passes (all adopted, below)
BLOCKED  0 new (G5-05 CHECK B still needs RC started with RC_ARENA_MODE_MODIFIERS=1)
```

## Live state (read-only probes)

- `/api/state`: `mode_key='client'`, `liveclient` empty, LCU phase `None` at 04:43 and on every re-poll
  (about every 2-5 min between steps). health.json pid 24124, alive, last_reload_ok true.

## Shipped (Tier-0 docs)

1. **RM-879 SHIPPED** - G5-05 CHECK B rewritten. Rows since RM-875 `f5782b25b` carry `enemy_stats` /
   `augments` / `engine_version` / `apply_mode_modifiers`. Older rows carry none and are never re-run,
   because the seam did not exist. `apply_mode_modifiers: true` is the flag proof. The re-run is
   `dispatch_for_coach` ON / OFF with `EnemyStats(**row)` against the `display_rows` order. The row
   records no self-HP, so that is the first suspect in a NEITHER result.
2. **G3-14 readied** (data read-only from the main checkout's `data/aram_coach_shadow.jsonl`):
   - The live ARAM prompt never emits `objective` (no Objective output field, not parsed), so
     objective agreement can never accrue (0 of 370 rows).
   - `tools/aram_shadow_report.py` measures neither R78 field. Filed **RM-882**.
   - `item_extra` agreement: 154 / 218 = 0.706 case-folded, 152 exact.
   - The deterministic objective took only 2 of its 6 branches over 3581 rows. Its tower-HP inputs are
     seeded 100 / 100 and kept across null vision reads.
   - CHECK written for the next ARAM game: the writer is alive, and the tower-HP value changes within
     90 s before to 60 s after a `TurretKilled`.
   - The RM-852 caveat is struck as resolved by RM-859.

## Gates

- Verifier pass 1 REFUTED three points, all adopted:
  - "5 games" was 6.
  - A bare `:534-535` cite resolved to the wrong file.
  - PASS could be met by a held stale value.
- Verifier pass 2 CONFIRMED those fixes and raised three nits, all adopted:
  - FAIL now needs the turret on screen below full HP.
  - The 154 is labelled case-folded, with 152 exact.
  - An unbalanced bold marker in BACKLOG is fixed.
- Doc guards: 40 test files that cite the touched docs, plus `tests/test_doc_size_budget.py`. First run
  1 failed / 783 passed. The cause: the new ROADMAP line made the known-broken `ROADMAP.md:231` cite
  resolve. Fixed by folding RM-882 into the RM-879 line (ROADMAP line count unchanged). Final result
  after the rebase is in the banner.

## Decisions recorded

- The objective half of G3-14 is NOT proposed for "Not actually live-gated". Haiku agreement there is
  impossible, but "does the deterministic objective track real towers" is genuinely live (vision-only
  inputs), so the row stays and is restated.
- RM-882 says not to add an Objective field to the live prompt to manufacture a baseline.
- Three small text fixes in LEDGER / BACKLOG were applied with a short Python replace, not the Edit
  tool (R1). They are backed by the commit diff.

## Merger follow-ups

- None needs a restart or a game. G5-05 CHECK B still needs an RC start with
  `RC_ARENA_MODE_MODIFIERS=1` before an Arena game can drain it.

## Next candidate

- RM-882 for the queue lane (Tier-1, `tools/aram_shadow_report.py`).
- GATE 3 in-game rows: G3-14 is now readied. The next unready ARAM row is G3-15 (re-check of GATE 2
  rows), which needs its GATE 2 parents' predicates.

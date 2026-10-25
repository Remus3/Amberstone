# Lane gated - run s133g007-ab356b (session 133, cycle 7, 2026-10-25)

No game this window: League client open at home, no lobby, no champ select, no game.

```
IN-GAME  0 min                                   |  IDLE whole cycle (02:43 to about 03:25 local)
DRAINED  0 rows                                  (GATE 1 re-read: every row needs a lobby or champ select)
READY    1 row: G5-05, split into CHECK A (stat half, drainable in any Arena game now) and
         CHECK B (coach half, after RM-875)
REFUTED  "DS restart" in G5-05 is stale (the seam is a per-request body key, not a DS flag);
         the first-draft CHECK was circular (it proved the flag was carried, not that the addends are right)
BLOCKED  G5-05 CHECK B waits on RM-875 (no live RC path sends apply_mode_modifiers)
```

## Live state (read-only probes)

- `/api/state`: `mode_key='client'`, `liveclient` empty, LCU phase `None` at 02:43, on every re-probe, and
  before the commit and the push.

## Prep shipped (Tier-0 docs, `d13523793` on origin/main, rebased from `0a44ef156` over batch F `742711129`)

1. **G5-05** (RM-172 `apply_mode_modifiers` Arena re-rank). The live Arena coach path
   (`coaches/arena_coach.py:699` -> `coach_integration/archetype_dispatch.py:360`) goes through
   `dispatch_for_coach` and `rank_for_primary_archetype`. `inspect.signature` gives neither the parameter;
   14 per-scorer client functions do have it. `core/focus_board_live.py:439` hard-codes False. Compute half
   (in-process, NOT evidence): 45 of 171 `wiki_stats` entries carry `ar` addends. `rank_items` at L9 with
   the flag ON vs OFF moves the full order for 42 and the top 5 for 6. `build_champion` L9 Vayne HP
   1240.52 -> 1173.12.
   - CHECK A: relay `activePlayer.championStats` maxHealth / attackDamage vs `build_champion` ON / OFF,
     with a gap-relative tolerance. NO RESULT is checked first; it covers Stat Anvils, unknown item ids,
     buffs and gaps that are too small.
   - CHECK B: the `ds_calibration.jsonl` ARENA `ds_picks` `item_id` order vs the ON / OFF re-runs. It is
     a wiring sub-check only.
2. **RM-875** filed in BACKLOG ("Session 133 lane filings (gated lane cycle 7)"): thread the flag through
   `rank_for_primary_archetype` and `dispatch_for_coach` behind a DEFAULT-OFF RC flag, and make the
   calibration rows record their re-run inputs. Indexed in the ROADMAP RM-14 fold line. Next free id RM-876.
   LEDGER 1840.

## Gates

- Verifier pass 1: REFUTE. CHECK circular, inputs not recorded, "matches neither" missing, id collision with
  in-session RM-872 / LEDGER 1835. All adopted.
- Verifier pass 2: REFUTE. CHECK A axis set unreadable, NO RESULT order unstated, Stat Anvils uncovered,
  origin moved (RM-872..874 and LEDGER 1835..1839 taken). All adopted; renumbered RM-875 / LEDGER 1840.
  Its numeric re-measure CONFIRMED every quoted figure.
- Doc guards: 38 test files citing the touched docs, plus the size-budget, RM registry and ROADMAP id guards.
  - Before the rebase: "746 passed, 295 subtests passed", EXIT=0.
  - On the rebased tree: "746 passed, 295 subtests passed", EXIT=0.
- Added lines: 0 non-ASCII. The only address is loopback. Pre-push: sibling sweep clean, 0 credential
  findings.

## Merger follow-ups

- None needs a restart or a game.

## Next candidate

- Origin's RM-873 (the G5-01 doc probe raises FileNotFoundError on an absent anvil file) sits in this lane's
  doc. It is a queue-lane-sized row.
- Every GATE 5 row is now readied or blocked with a named prerequisite.

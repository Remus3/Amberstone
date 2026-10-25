# Lane gated - run s133g005-5f4047 (session 133, cycle 5, 2026-10-25)

No game this window: League client open at home, no lobby, no champ select, no game.

```
IN-GAME  0 min                                   |  IDLE whole cycle (00:43 to about 01:05 local)
DRAINED  0 rows                                  (the idle LCU state at home answers no row)
READY    3 rows: G5-01 anvil half, G5-09, G5-03   (GATE 5 DRAIN CARD: baselines, probe, predicate)
REFUTED  3 stale claims fixed in place: G5-01 "anvil file STILL ABSENT" (it exists, all leakage),
         GATE 5 "restart RC-LCUAgent before playing" (now conditional), G5-02 "re-home first" (done)
BLOCKED  G5-04 (no /rank plumbing, unchanged); G5-05 / G5-06 / G5-08 not readied this cycle
```

## Live state (read-only probes)

- `/api/state`: `mode_key='client'`, `liveclient` empty, LCU phase `None` at 00:43, 00:46 and before the push.
- health.json pid 12628 alive, last_reload_ok True.
- RC-LCUAgent pid 18860 created 2026-10-25 00:27, after the newest `tools/lcu_agent.py` commit (`6e2b4359f`, 2026-10-24 23:25).

## Prep shipped (Tier-0 docs, `9b74bdbb9`, pushed ff to origin/main)

1. **G5-01 predicate poisoned, RM-867 filed.** `data/anvil_shadow.jsonl` now exists (30 rows, 16260 B), and the
   row's check ("the file exists, and augment_shadow grew past 966 B") is already true. But all 30 rows are one
   test fixture (Lux, round 3, owned Boots, an RM-364 injection offer, take `X`, 2026-09-06..09-11), written by
   `tests/test_rm364_prompt_sanitizer_population.py` before RM-406 (`88625e224`) added the redirect. No real anvil
   row has ever been written. The new predicate needs a row whose ts, champion and offered cards match the live game.
2. **GATE 5 DRAIN CARD:** baselines plus one-line probes for G5-01 (anvil), G5-09 (precheck: `augments_picked`
   holds api names, `item_build` is a display-name string; the pass is decided by the rendered panel, and an empty
   panel counts as no result) and G5-03 (uses the G5-01 probe).
3. Stale cites fixed: the RC-LCUAgent restart now runs only if a check fails; G5-02's chain is already re-homed
   (`tools/lcu_agent.py:800-849`); G5-04's conclusion holds, with its cites moved to `core/daemon_slayer_client.py:2013`
   and `agents/daemon_slayer/server.py:2049-2053`.
4. LEDGER 1826. Next free id RM-868. Ids were renumbered after the rebase: the research lane took RM-866 and
   LEDGER 1825 at 00:43. No count moved.

## Gates

- Independent read-only verifier: claims 1-5 and 7-9 CONFIRM, and it checked that the test can no longer write
  the live file at HEAD. It found three problems, all fixed before commit: an id collision (renumbered), a range
  cite of 800-846 that should be 800-849, and G5-09 trigger wording ("134" changed to `DrawYourSword`, plus the
  empty-panel rule).
- Doc guards: 38 test files that cite the five touched docs, run on the pre-rebase tree and again on the rebased
  tree: "746 passed, 295 subtests passed", EXIT=0 both times.
- Added lines: 0 non-ASCII, 0 CR. Pre-push sibling sweep clean, credential scan 0 findings.

## Merger follow-ups

- None for this cycle. RM-867 is queue data work (archive split under the data-fix doctrine, census of the other
  RM-406 shadow paths). Note that `coaches/arena_coach.py` is currently in lane_exclusions; RM-867 does not need it.

## Next candidate

- Arena game: run the GATE 5 DRAIN CARD (G5-01 anvil, G5-09, G5-03). ARAM: G3-03 at champ select.
- Next idle prep: G5-05 / G5-06 / G5-08 readiness (DS flag or replay design), or the G3-15 cross-checks.

# Lane gated - run s133g003-a9d850 (session 133, cycle 3, 2026-10-24)

No game this window: League client open at home, no lobby, no champ-select, no game.

```
IN-GAME  0 min                                   |  IDLE whole cycle (from 22:43 local)
DRAINED  0 rows                                  (no row is answered by the home / idle LCU state)
READY    2 rows: G3-12, G3-10                    predicate / field path / precondition written in the doc
REFUTED  1 claim corrected (my own G3-12 draft)  the 45 s ceiling is not the binding lag term
BLOCKED  G3-12 waits on RC running with RC_ARAM_STATE_DEBOUNCE=1 (operator / merger act)
```

## Live state (read-only probes)

- `/api/state`: `mode_key='client'`, `liveclient` empty, LCU phase None at start, mid-prep and before commit.
- health.json alive, last_reload_ok; DS :8860 1.290.0 / 16.21.1; `tools/gated_live_probe.py` IN-GAME False.

## Prep shipped (Tier-0 docs, `f12158ee9`, pushed ff to origin/main)

1. **G3-12** (`RC_ARAM_STATE_DEBOUNCE` DEFAULT-ON): `BACKLOG.md:64` cite dead (origin LEDGER 506 / 507);
   flag read once at import (`coaches/aram_coach.py:62`), unset at User and Machine scope, set by no
   launcher; replay alternative has no input (no `ARAM Haiku raw` line in the 15 retained day logs).
   CHECK: proof-of-ON = the debug skip line (`:1082`) in the day log; PASS iff
   `data/aram_coaching_data.json` `game_time_s` never trails `liveclient.game_time_s` by more than 90 s
   while alive; lag with a Haiku error / budget / kill-switch line = INCONCLUSIVE.
2. **G3-10** (Leona `assume_ally_detonation`): still no caller outside three DS engine files; note cites
   16.13.1 vs DS 16.21.1; the 16.21.1 text is the same Meraki-frozen string; no known probe counts mark
   consumption (inference - check the live `eventdata` list once in any game).
3. LEDGER 1813. No RM id minted, no count moved.

## Gates

- Adversarial verifier (independent, read-only): PARTIAL - all citations CONFIRMED; G3-12 lag bound and
  FAIL clause corrected, G3-10 per-hit claim relabelled as inference. Corrections adopted before commit.
- Doc guards this run: 29 test files citing the two docs + `test_rm_id_registry_drift.py` +
  `test_roadmap_rm_ids_unique.py`: "659 passed, 273 subtests passed", EXIT=0.
- Added lines: 0 non-ASCII, 0 CR. Pre-push sibling sweep + credential scan clean.

## Merger follow-ups

- To drain G3-12: restart RC with `RC_ARAM_STATE_DEBOUNCE=1` before an ARAM session (not a lane act).

## Next candidate

- Next idle prep: G3-13 (augment reco on-screen) - re-check the `screen_read` staleness candidate blocker
  and the `66e6835e` fast-poll gate at HEAD.

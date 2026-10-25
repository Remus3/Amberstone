# Lane gated - run s133g002-db5324 (session 133, cycle 2, 2026-10-24)

No game this window: League client open at home, no lobby, no champ-select, no game.

```
IN-GAME  0 min                                   |  IDLE ~whole cycle (from 21:43 local)
DRAINED  0 rows                                  (no row is answered by the home / idle LCU state)
READY    1 row: G3-16                            predicate + one-line probe + fail form written in the doc
REFUTED  1 claim killed (my own): the 282 post-08-02 ARAM shadow rows are NOT missed live games
BLOCKED  0 rows newly; G3-14 accrual gets a caveat until RM-852 lands
```

## Live state (read-only probes)

- `/api/state`: `mode_key='client'`, `liveclient` empty, LCU phase `None`; health.json alive, last_reload_ok.
- `python tools/gated_live_probe.py`: `IN-GAME: False`, gate GATE 1.

## Prep shipped (Tier-0 docs, `9c46e6e97`, pushed ff to origin/main)

1. Duplicate id: `docs/LIVE_GAME_GATED_SYNC.md` carried two "G3-14" rows. The `hz_choice_shadow` game_id row
   (filed by `0dc5dbd0d`, 2026-08-12) is now **G3-16**. Its commit never touched the count line, so it stays
   outside the OPEN 111, like G6-04. No count moved.
2. **G3-16 READY**: PASS iff a row after game start has `game_id` matching `^[0-9]+$` and
   `game_run_id == game_id`; FAIL if `game_run_id` starts `local-` while the LCU phase is `InProgress`.
   The probe is one python line in the row. Cite drift fixed (`lcu/snapshot_shape.py:543-557`).
   `data/hz_choice_shadow.jsonl` has had no live row since 2026-08-02T22:34:15Z.
3. **G3-14 (C17) accrual caveat + RM-852**: all 282 `data/aram_coach_shadow.jsonl` rows since 2026-08-03 have
   `enemy_comp == []`, champ Kai'Sa and one distinct `live_haiku` block (669 enemy-less rows in total).
   `tools/aram_shadow_report.py` counts them toward the flip. Filed RM-852 (BACKLOG
   "Session 133 lane filings (gated lane cycle 2)", ROADMAP NOW); the tracker pin moved to RM-853. LEDGER 1807.

## Gates

- Self-adversarial: my first reading ("live ARAM games the hz_choice writer missed") was killed by the empty
  enemy list plus one champion across 21 days; no writer-outage row was filed.
- Read-only verifier (independent): CONFIRM on all 7 items (dup id, citations, data counts re-derived, no
  tick, RM-852 unique, ASCII/LF/no leaks). Both wording nits adopted.
- Guards this run: `tests/test_rm_id_registry_drift.py` + `tests/test_roadmap_backlog_disposition_drift.py`
  + `tests/test_roadmap_rm_ids_unique.py`: "64 passed, 33 subtests passed", EXIT=0.
- Pre-push: the sibling sweep and the credential scan were clean.

## Merger follow-ups

- None: no restart, no live write, no code change.

## Next candidate

- RM-852 for the queue lane (Tier-1; trace the enemy-less `aram` tick before choosing writer vs report fix).
- Next idle prep: G3-12 (debounce DEFAULT-ON) - check whether `RC_ARAM_STATE_DEBOUNCE` default and the
  replay-feed alternative named in the row still exist at HEAD.

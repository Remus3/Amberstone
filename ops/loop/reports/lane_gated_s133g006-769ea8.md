# Lane gated - run s133g006-769ea8 (session 133, cycle 6, 2026-10-25)

No game this window: League client open at home, no lobby, no champ select, no game.

```
IN-GAME  0 min                                   |  IDLE whole cycle (01:43 to about 02:05 local)
DRAINED  0 rows                                  (the idle LCU state at home answers no row)
READY    2 rows: G5-06, G5-08                    (CHECK, field path and predicate written in each row)
REFUTED  2 stale claims fixed in place: the G5-08 item name (444644 is Crown, not Celestial
         Opposition) and "the replay corpus satisfies the debounce flip headless" (no input at HEAD)
BLOCKED  G5-06 waits on RC running with RC_ARENA_STATE_DEBOUNCE=1 (operator / merger act);
         G5-08 CANDIDATE waits on RM-871 step 1 (CommunityDragon read) and a human move;
         G5-05 still not readied (needs a DS flag design)
```

## Live state (read-only probes)

- `/api/state`: `mode_key='client'`, `liveclient` empty, LCU phase `None` at 01:43, 01:47, 01:48 and before the commit.
- health.json pid 18164 alive, last_reload_ok True.

## Prep shipped (Tier-0 docs, `0005c494f`, rebased from `e957bcae7`)

1. **G5-06** (`RC_ARENA_STATE_DEBOUNCE` DEFAULT-ON). The replay alternative has no input. There is no Arena
   coach replay tool, none of the 15 retained day logs has an Arena coach line, and
   `data/arena_coach_shadow.jsonl` (617 rows) lacks the signature fields. The flag is read once at import
   (`coaches/arena_coach.py:68`), it is unset at User and Machine scope, and no launcher sets it.
   CHECK: proof-of-ON = the `:795` debug skip line. PASS iff `data/arena_coaching_data.json`
   `game_time_s` never trails `liveclient.game_time_s` by more than 150 s while alive. The ARAM 90 s
   bound does not carry over: the Arena signature has no game-time band, and the worst case is about 91 s
   single-attempt, more with an SDK retry. The FAIL excuses are named, including the silent budget and
   kill-switch gates.
2. **G5-08**. The row names the wrong item: 444644 is Crown of the Shattered Queen. DDragon 16.21.1 says 90% /
   1.25 s; Meraki (content 25.15) says 50% / 3 s. RM-808 decides which source DS seeds from, not the
   in-game value, so the deciding headless read is CommunityDragon 16.21 game data (RM-871 step 1,
   mandatory). Filed as a "Not actually live-gated" CANDIDATE, plus a one-glance tooltip cross-check.
3. The "Not actually live-gated" debounce entry is marked NOT TRUE AT HEAD for both flags.
4. RM-871 filed in BACKLOG: seed 444644 in `_item_general_dr.py` once CommunityDragon confirms. ROADMAP
   indexes it in the gated lane's RM-867 line, because ROADMAP sat 16 bytes under its 81920-byte budget
   (`tests/test_doc_size_budget.py` went red on a separate line). LEDGER 1834 (renumbered from 1831 at the
   rebase over the batch E merger's 1831-1833). Next free id RM-872.

## Gates

- Independent read-only verifier: REFUTE on the first draft. It found that RM-870 was taken, the `_run_coach`
  gate is at `:631`, the vision read runs on `_vision_loop`, the lag derivation and OFF baseline were wrong,
  the FAIL clause waited on gates that log nothing, and the CANDIDATE wording presented a source rule as
  the in-game value. Every correction was adopted and its new cites spot-checked before the commit.
- Doc guards: the 38 test files citing the touched docs plus `test_rm_id_registry_drift.py` and
  `test_roadmap_rm_ids_unique.py`: "746 passed, 295 subtests passed", EXIT=0 before the rebase. The first
  run after the rebase gave "1 failed, 745 passed" (`test_roadmap_md_under_budget`, 82157 > 81920). After
  the ROADMAP fold: "746 passed, 295 subtests passed", EXIT=0.
- Added lines: 0 non-ASCII, 0 CR, no machine path / host / address / email.

## Merger follow-ups

- RM-870 landed on origin during this cycle (`3ee954531`, LEDGER 1831-1833). The lane rebased over it,
  so RM-871 and LEDGER 1834 are free on origin at push time.
- ROADMAP has 9 bytes of headroom (81911 of 81920). The next filing from any lane needs a size-budget
  relocation to `docs/ROADMAP_HISTORY.md` (a merger act).
- A stray scratch write happened this cycle and was undone: a pytest output file landed briefly in the
  main checkout at `ops/loop/reports/_unused` (a relative-path mistake). It was the lane's own file,
  created at 02:01, and was removed within the same minute. Nothing else in the main checkout was touched.

## Next candidate

- G5-05 (`apply_mode_modifiers` Arena re-rank) is the last GATE 5 row not readied. It needs a DS-flag and
  restart design first.

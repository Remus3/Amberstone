# Amberstone - next session: FORK ON LIVE STATE, do not pick blind

Mirrors the Desktop hand-off at `C:\Users\Administrator\Desktop\RC-NEXT-SESSION.txt`.
Read `git log --oneline` rather than trusting any list below.

## PROBE FIRST

- `curl -k https://127.0.0.1:8888/api/state` - `mode_key`
- `curl http://127.0.0.1:8860/health` - DS, **plain HTTP not HTTPS**
- `ops/runtime/health.json` - pid, alive, last_reload_ok
- `gh run list --limit 5` - **see "CI IS BLIND" below FIRST**

## FORK

- **FORK A, a game is playable (ARAM Mayhem preferred, else SR):** close the
  RM-01 A/B agreement blocker. Still the single highest-value live-gated row,
  still UNBLOCKED on the log side, still NOT closed - run 2026-08-06-01 was
  client-only and never had a game to use. Play ONE ARAM on a RESTARTED RC
  process, then `python tools/aram_raw_replay.py` and check
  `data/aram_coach_shadow.jsonl` for `live_choices > 0` and both > 0.
  **TRAP IN THAT TOOL, unchanged and still live** - do NOT widen its scan
  without reading this: `discover_logs` uses `logs_dir.iterdir()`,
  NON-RECURSIVE, so it deliberately misses `logs/agents/supervisor.log*`. Those
  hold 611 further `ARAM Haiku raw` records that are SYNTHETIC STUBS - all
  exactly 235 chars, none truncated, all `Choices: []`, byte-identical. Widen
  the scan and 611 stubs land in the "complete" bucket and read as genuine model
  omission. Pair this fork with RM-168 (the in-game log-rate sample).
- **FORK B, client up but no game:** take RM-163, the Riot NEGATIVE-CACHING gap.
  Highest-value non-gated row open, fully headless, and the ROOT CAUSE behind a
  symptom the last run only masked.
- **FORK C, neither / RC down:** RM-158's data half, or RM-167.

## READ THIS FIRST - things that make the obvious reading WRONG

1. **CI IS BLIND FOR THE LAST RUN'S COMMITS, AND IT IS NOT A REPO FAULT.**
   GitHub Actions was in a MAJOR OUTAGE from 2026-08-06 15:22:49 UTC (impact
   critical, webhook delivery delays), so six pushed commits created ZERO
   workflow runs: `53bd3bb1`, `e97cefec`, `ab9b2b18`, `fe1628e2`, `d90f8a16`,
   `48c3cfce`. `gh run list` just shows the previous day and reads exactly like
   a broken trigger. **ALREADY RULED OUT, do not re-probe:** Actions enabled
   (`actions/permissions` -> `enabled true`, allowed all), all 3 workflows
   `state=active`, `ci.yml` `paths-ignore` is `**/*.md` ONLY while every push
   carried `.py`, and the commits ARE on GitHub. **NOT ruled out: BILLING** -
   the local `gh` token carries `gist`/`read:org`/`repo`/`workflow`; the usage
   endpoint needs `user` and 404s with a scope hint, and refreshing it needs
   interactive auth, so exhausted minutes is UNPROBED rather than excluded. A
   manual `gh workflow run ci.yml --ref main` DID create run `31127029404`,
   isolating the failure to push-event delivery rather than run creation.
   **FIRST ACTION: re-probe `gh run list --commit <sha>` for all six.** Every
   merge passed a LOCAL gate only (ruff + a pytest subset + `drift_guard` 0
   breaches). That is NOT equivalent to CI - do not read the run as CI-green.
2. **THE `Co-Authored-By` TRAILER IS STRIPPED BY POLICY - never treat its
   absence as a defect.** `.githooks/commit-msg:23-29` deletes
   `^Co-Authored-By: Claude` per operator policy 2026-06-03. Deletion, not
   rejection, which is why it reads as an authoring omission. Last run this cost
   real work: 3 slice prompts told agents to add it, TWO verifier passes
   returned REFUTE on it as a real finding, and two merge bodies (`53bd3bb1`,
   `e97cefec`) contain sentences asserting they carry a trailer the hook then
   removed - those sentences are WRONG and are left in history rather than
   rewritten. Audit with an ANCHORED predicate: `grep -ci 'Co-Authored-By'`
   returns 1 for two commits that do NOT carry it, matching prose ABOUT the
   trailer. Read the message TAIL. Now also a CLAUDE.md hard rule.
3. **THE ARENA LANING TABLE IS ROOT-CAUSED AND FIXED, BUT THE DATA IS STILL
   CORRUPT.** RM-158 closed its code half at `53bd3bb1`:
   `core/lead_projection.py` registered gold-income rates for SR and ARAM only,
   so `gold_income_per_min("ARENA")` fell through to a default byte-identical to
   the SR rate (450.0). At schema v3 (itemless) that was ARENA's LAST
   mode-differentiating input, so the generator computed SR content and wrote it
   under an arena header. Fixed by registering the ARENA row and making `main()`
   REFUSE to write a mode whose income row is unregistered. **WIDER THAN
   FILED:** BOTH shipped arena tables are SR copies - 16.12.1
   (`cec62070b61e7c35`, 66,197,973 B) as well as 16.13.1 (`22982424e69c42cc`,
   66,961,516 B), hashes re-derived independently. **STILL OWED:** a regen, and
   `data/hz_choice_shadow.jsonl` carries 1,148 `mode=arena` rows that are SR
   measurements labelled arena - DROP or RELABEL, never average. Blast radius
   was contained: the only live reader is a discard-return shadow logger, so the
   corrupt table never reached the coach UI.
4. **THE SUITE COUNT IS NOT STABLE AND A FEW FAILURES ARE NOT A REGRESSION.**
   18215 / 18221 / 18222 / 18234 / 18258 measured 2026-08-04 across
   near-identical trees, 0-3 failures with DISJOINT failing sets (mission_control
   socket WinError 10053, snapshot_panels playwright timeouts, pgr/adversarial
   panel snapshots). Check DISJOINTNESS across two runs before calling anything a
   regression. A verifier measured collection at 18637 on 2026-08-06 and
   reconciled 18489 passed + 148 skipped exactly, so growth is real and the range
   has moved up.
5. **FIVE CONCURRENT PYTEST PROCESSES DEADLOCK ON THIS BOX.** A sixth HANGS
   rather than failing. xdist also dies with `INTERNALERROR: Unexpectedly no
   active workers` alongside a big file-writing job. Under parallel slices use
   plain `-q` with NO `-n`; `-n 4 --timeout=300` is the ceiling when alone.
6. **DS CAN WEDGE WITH EVERY SIGNAL GREEN and is NOT supervisor-watched.** Task
   Running + port LISTEN + a live pid can all read fine while every HTTP
   connection is refused. ALWAYS probe `:8860` with a real HTTP call. Recovery:
   `taskkill /F /PID <owner>`, confirm the port freed, then
   `schtasks /Run /TN RC-DaemonSlayer`. Never `Stop-Process`. Run those two
   through PowerShell, NOT the Bash tool - MSYS rewrites `/F` to `"F:/"` and
   `/TN` to `"C:/Program Files/Git/Run"`. Same family: `gh api /users/...` with
   a LEADING SLASH becomes `"C:/Program Files/Git/users/..."` - omit it.

## CONTEXT

HEAD `b12f3291`. **ENGINE_VERSION 1.275.3**
(`agents/daemon_slayer/__init__.py:18`) - BUMPED THREE TIMES on 2026-08-08,
patch 16.15.1, DS `:8860` bounced and serving 1.275.3 (probed, not assumed).
The lane-6 DS run landed `e4260948` (RM-176: the `_recharge_to` charge-remainder
discard plus the extra-shot effect-crit basis, both opt-in paths) and
`1c1291ea` (RM-177: heal-and-shield-power composes ADDITIVELY - the one
DELIBERATE default-output move, `/api/spike-curve` amp 1.3552 -> 1.3200).
The third bump is `a757eae4` (Obsidian Cleaver Carve four patches stale,
0.35 -> 0.30). Detail: LEDGER 1231-1232 and 1233-1236.

## ACCEPTANCE

- **FORK A** - `live_choices > 0` in `data/aram_coach_shadow.jsonl` after one
  live ARAM on a restarted process; then RM-01's A/B half is finally adjudicable.
- **FORK B** - the negative-caching gap fixed at the `riot_api` layer, with a
  test proving a `None` result is cached and does NOT refire, plus a measurement
  of `/api/last-match` COLD latency before and after (cold is the number that
  moves; the 30s response cache already handles repeats).
- **FORK C** - per row.

## ALSO OWED, in priority order

1. **RM-163 RIOT NEGATIVE CACHING - the real cause of the 320ms, still
   unfixed.** `core/riot_api.py:520-522` does `data = _call(...)` then
   `if data is not None: get_cache().set_immutable(...)`. A `None` is NEVER
   stored, so a match Riot legitimately has no timeline for refires the outbound
   call on EVERY request, forever. Measured: 289ms of 291ms of an
   `/api/last-match` build was that one urlopen, via
   `dashboard/builders_lcu_enrich.py:407 _attach_match_timeline` ->
   `core/riot_api.py:504 get_match_timeline`; 4 consecutive builds at
   370/296/339/325ms, ZERO cache hits. This affects EVERY Match-V5 consumer, not
   one route. Note event modes (ARAM Mayhem `gameMode=KIWI`, queue 2400)
   returning empty is EXPECTED AND PERMANENT, so `None` is the normal case, not
   an error path. The cache shipped last run MASKS this - cold is still ~475ms
   (measured live post-restart: 0.475s cold, 0.0076-0.0081s cached).
2. **RM-164 LANE B IS BLOCKED ON A CONSUMER, NOT ON DATA.** The HZ-B1
   comp-archetype build-order table is the largest and richest of three families
   (692 cells/mode; flat 519; durability variants 346, all full and
   machine-guarded at a 1.0 coverage floor) and has ZERO PRODUCTION CONSUMERS -
   a verifier narrowed the reference set to the definition plus 5 test call
   sites, with nothing under `tools/` or `ops/audit/` at all. Live readers use
   the shadow-only 2-class variants table or the flat table. So the richest
   precomputed build data RC holds is on no path a coach reads, and Lane B cannot
   retire a Haiku call on it until a consumer is wired - a coach-surface change.
   Related, consumer-side: `core/next_buy_fallback.py:70` hardcodes
   `_PREFERRED_BUCKET = "balanced"` and discards the flat table's AD/AP lean on a
   LIVE liveclient path; and no table cell records the scorer archetype it was
   ranked under, so a consumer cannot detect staleness against an operator
   archetype override. That last one is the failure most likely to make a future
   flip unsafe. **DO NOT wire `sort_by="efficiency"` as the ordering metric** -
   MEASURED and REJECTED 2026-08-06: it changed 52 of 60 cells over 15 champions
   x 4 comp archetypes and pulled Doran's Helm / Doran's Bow / Guardian's Blade
   into slots 3-5 of the final six. It DEGRADES the tables. The starter-tier
   invariant is now pinned by `tests/test_build_order_starter_tier_guard.py`
   (`Lane` tag AND gold < 1000; 78 Lane-tagged, 76 under 1000g, exactly 2 above
   at 2500g, and NO Lane item between 950g and 2500g so the ceiling sits in an
   empty band). Note the starter leak is in the engine too - `_filter_candidates`
   at `agents/daemon_slayer/rank.py:687` has no starter gate - which may be
   CORRECT for early next-buy advice, so it wants an operator call, not a
   unilateral deny.
3. **RE-RUN `python tools/repair_spend_ledger.py` ONCE.** It is idempotent.
   Three other worktrees carried the unpatched conftest during the run, so
   today's ledger file may have accrued more synthetic rows. Background: RC's
   cost ledger was polluted by tests driving the REAL cost tracker. Measured 40
   of 84 day-files, 13,141 synthetic calls, $1.156408, all at exactly 10-in /
   20-out under `aram_coach` / `arena_coach`. Real spend after repair:
   $128.115777 / 56,026 calls. **THE CONSUMER IMPACT IS THE HEADLINE** -
   `tools/cost_health_watchdog.py`'s trailing-median daily baseline was
   $0.039424 against a true $0.300906, 7.63x low and composed ENTIRELY of test
   rows, so the instrument the whole cost program reads was calibrated on fake
   data. Backup of the pre-repair ledger is in the session scratchpad under
   `spend_backup_20260806`; `data/spend/` is GITIGNORED so the repair is machine
   state no commit records. **STILL UNIDENTIFIED, do not accept a guess:** two
   all-zero `by_gate` records in `recent_matches.json` at 2026-08-04 22:16:28,
   41ms apart. The first attribution (`test_last_match_ingest_gameid.py`) was
   REFUTED by measurement - that file never calls `save_match`, and NO test in
   `tests/` does. The mechanism (`core/match_db.py:177` on every saved match) is
   real and containment is proven; only the producer is unknown. See also RM-165.
4. **RM-167 NEEDS-OPERATOR - the aram prompt-cache hoist, worth roughly 10-15
   pct of total spend.** MEASURED: across 51 real ledger days, 38,319 calls and
   62.1M input tokens, `cache_in = 126` and `cache_write = 126` (0.0002 pct).
   The 12 `cache_control` markers in the tree are INERT because every marked
   prefix sits below its model's cache floor - aram `_SYSTEM` static tail is 6177
   chars (~1670 tok vs the 2048 Haiku floor), arena 3082, vision 616 (vs 1024).
   Worse, `coaches/aram_coach.py:920` interpolates all 5 placeholders into the
   FIRST 145 chars of `_SYSTEM`, so the marked prefix mutates every tick.
   Hoisting yields a stable 6177-char prefix that STILL misses the floor by ~380
   tokens, so it needs deliberate padding - and moving instructions shifts Haiku
   positioning, so behavioural equivalence needs a live ARAM A/B. **NOT covered
   by the item-286 closure**, which only measured the four augment/TFT prompts.
   Also unmeasurable offline: the real token count of that static tail
   (estimates span 1670 to 3089, straddling the floor). A live `count_tokens`
   settles it.
5. **RM-155** - decide whether to build a native per-mode corpus so aram/arena
   can be measured at all, or retire the laning-verdict flip outright.
   Arena-flavoured work was blocked on RM-158, which is now root-caused, but the
   DATA is still corrupt (item 3 in READ THIS FIRST), so a native arena gate
   number is still not obtainable.
6. **RM-166** - `web/js/panels/last_match.js:385` holds a SECOND copy of the
   `(5, 50)` baseline clamp bounds. Pre-existing (`ecb5c630`, 2026-05-16), a
   different language so no Python extraction could single-source it, and the
   server clamp is authoritative - but a real future-divergence site.
7. Two sub-degrades in `dashboard/builders_last_match.py` return `found=True`
   with NO error key and so ARE cached for 30s: the swallowed `raw_data` JSON
   parse and the Match-V5 timeline placeholder path. Both durable rather than
   transient, so defensible - on record, not a bug.
8. **RM-165** - `tools/cost_health_watchdog.py` globs `*.json` over the spend
   dir and reads `_match_open.json` as a DAY-LEDGER. It carries a `by_purpose`
   block and sorts LAST (`_` 0x5F > `2` 0x32), displacing a genuine sample out
   of `prior[-7:]`. INERT only because that file is now `{}`; it refills on the
   next real match save.
9. **RM-168** - the log-rate sweep could only sample an IDLE client
   (mode=client, no game, no dashboard tab): 0.0475 lines/s overall, worst
   unsuppressed path 0.031/s. The interesting case - in-game, multi-tab, where
   the suppression list's own comment says the 2 Hz volume lives - is UNMEASURED.
   Pair it with FORK A.
10. **RM-154 deployment tail:** `_LOG_FILE` resolves via `__file__.parent.parent`,
    so agent copies deployed to `C:\RC-Agent\` write `C:\logs\<agent>.log`.
    Follows the shipped `liveclient_relay` precedent; wants an operator decision.
11. `tools/aram_raw_replay.py` has NO `# arch:` header. Adding one forces a
    `docs/ARCHITECTURE.md` archmap regen - do it single-threaded, it is a
    shared-file collision risk during a parallel run.

## DO NOT REDO

- **The Lane A laning-verdict flip gate.** SR L6 n=1107, agreement
  0.48870822041553746, Wilson [0.45935, 0.51814], WORSE than the June 0.4955,
  every mode/level CI straddling 0.50. Base-rate census (decisive 0.5548,
  predictor favours a 48.1 pct vs label 50.2 pct) proves genuine ZERO mutual
  information, NOT a miscalibrated harness. Do not re-run it hoping for a better
  number and do NOT build the deferred ~190 MB/mode v4 regen.
- **`item_state` as a gate axis.** INERT on every shipped table - all schema v3
  where the cd node IS the leaf, so descend-only returns the same cell.
- **`--mode` as a corpus switch.** It swaps the TABLE only;
  `select_sr_match_ids` is `WHERE game_mode = 'CLASSIC'` unconditionally
  (`tools/replay_matchup_validate.py:184-196`). ARAM has NO native gate
  measurement - do not report one.
- **"SR is stranded on 16.12.1"** - WRONG, 16.13.1 ships all three modes.
- **`sort_by="efficiency"` as the build ordering metric** (item 2 above,
  measured).
- **RM-159 / making `tools/stop_claim_gate.py` negation-aware.** CLOSED BY
  MEASUREMENT, two refuted attempts. The gate audits the agent's own prose and
  the agent writes the prose, so any prose-level inference is gameable by the
  writer. It stays STRICT and the retraction false positive is ACCEPTED. It
  fired on every stop of the 2026-08-06 run against one historical sentence and
  a real merge commit did not clear it. Do not touch it.
- **The 89 recorded Haiku responses as evidence about the model.** ALL 89 were
  log-truncated at 600 chars (declared min 1113 / max 2029), so zero are
  evidence about the model or the parser.
- **`dashboard/_champ_select.py` as a Haiku call site** - it has none. The
  surviving champ-select site is `coaches/champ_select_coach.py:142`.
- **RM-151** (live-gated by its own acceptance), **RM-149** (needs two operator
  rulings), **RM-122 / RM-125** (operator-present rendered-pixel lane, explicitly
  fenced from the headless loop).

## OPERATOR DECISION STILL PENDING

Deliberately untouched for a third run: 3.72 GB of `rewind_history.db` backups
(11d / 16d, zero readers) plus 24.6 MB tier-2 and 137 MB tier-3. Nobody has
ruled on it. `core/data_retention.py` reports and declines; `apply()` is INERT.

## START WITH

`/clear`, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES + `git log`.
Then PROBE LIVE STATE before picking a fork.
